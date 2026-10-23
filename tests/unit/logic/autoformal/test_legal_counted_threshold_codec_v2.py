"""Finite three-target codec/prefix controls; no numerical or legal authority."""
from copy import deepcopy
import hashlib
import inspect
import itertools
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_counted_threshold_codec_v2 as subject
from ipfs_datasets_py.logic.autoformal import legal_counted_frame_threshold_v2 as factory
from ipfs_datasets_py.logic.autoformal import legal_counted_frame_v1 as legacy


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def no_authority(report):
    assert report["authority"] and all(value is False for value in report["authority"].values())
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0


def lexical_reference(raw):
    """Independent JSONDecoder-based scanner, without the producer regex."""
    text = raw.decode("utf-8")
    decoder = json.JSONDecoder()
    offset, tokens = 0, []
    while offset < len(text):
        char = text[offset]
        if char == '"':
            value, end = decoder.raw_decode(text, offset)
            assert type(value) is str
            tokens.append(text[offset:end]); offset = end
        elif char in "{}[],:012345":
            tokens.append(char); offset += 1
        else:
            raise AssertionError("unexpected canonical counted JSON character")
    assert "".join(tokens).encode("utf-8") == raw
    return tokens


def compact_nodes(tree):
    yield tree
    kind = tree[0]
    children = tree[3:4] if kind == "forall" else tree[2] if kind == "predicate" else [] if kind == "variable" else tree[1:]
    for child in children:
        yield from compact_nodes(child)


@pytest.fixture(scope="module")
def language():
    codec = subject.build_counted_threshold_token_codec_v2()
    codec_sha = subject.counted_threshold_token_codec_sha256(codec)
    cases = []
    for maximum in (1, 2, 3):
        request = factory.authored_counted_threshold_request_v2(maximum)
        raw = wire(request)
        encoding = subject.encode_counted_threshold_tokens_v2(raw,
            expected_request_sha256=sha(raw), codec=codec, expected_codec_sha256=codec_sha)
        context_raw = encoding["context_raw_utf8"].encode("utf-8")
        decoding = subject.decode_counted_threshold_tokens_v2(encoding["target_ids"], context_raw,
            expected_context_sha256=sha(context_raw), codec=codec, expected_codec_sha256=codec_sha)
        cases.append(dict(maximum=maximum, request=request, request_raw=raw,
                          encoding=encoding, decoding=decoding))
    assert len({case["encoding"]["context_raw_utf8"] for case in cases}) == 1
    context_raw = cases[0]["encoding"]["context_raw_utf8"].encode("utf-8")
    return dict(codec=codec, codec_sha256=codec_sha, cases=cases,
                context_raw=context_raw, context_sha256=sha(context_raw))


def decode(language, ids, **changes):
    args = dict(generated_ids=ids, context_raw=language["context_raw"],
        expected_context_sha256=language["context_sha256"], codec=language["codec"],
        expected_codec_sha256=language["codec_sha256"])
    args.update(changes)
    return subject.decode_counted_threshold_tokens_v2(**args)


def prefix(language, ids, **changes):
    args = dict(prefix_ids=ids, context_raw=language["context_raw"],
        expected_context_sha256=language["context_sha256"], codec=language["codec"],
        expected_codec_sha256=language["codec_sha256"])
    args.update(changes)
    return subject.inspect_counted_threshold_prefix_v2(**args)


def oracle(language, ids):
    matches = [case for case in language["cases"] if case["encoding"]["target_ids"][:len(ids)] == ids]
    allowed = sorted({case["encoding"]["target_ids"][len(ids)] for case in matches
                      if len(ids) < len(case["encoding"]["target_ids"])})
    return matches, allowed


@pytest.fixture(scope="module")
def all_states(language):
    prefixes = {tuple(case["encoding"]["target_ids"][:end]) for case in language["cases"]
                for end in range(len(case["encoding"]["target_ids"])+1)}
    states = []
    for offered in sorted(prefixes, key=lambda row:(len(row), row)):
        ids = list(offered)
        report = prefix(language, ids)
        states.append(dict(prefix_ids=ids, report=report))
    return states


def test_codec_distinct_profile_reuses_only_twenty_seven_lexical_spellings(language):
    codec = language["codec"]
    old = legacy.build_counted_frame_token_codec_v1()
    assert codec["schema"] == "legal-counted-threshold-token-codec/v2"
    assert codec["profile"] == "authored-one-to-three-many-sorted-compact/v2"
    assert codec["content_schema"] == "legal-counted-threshold-content/v2"
    assert codec["context_schema"] == "legal-counted-frame-signature-context/v2"
    assert codec["vocabulary_size"] == len(codec["vocabulary"]) == 28
    assert codec["vocabulary"][:3] == ["<pad>", "<bos>", "<eos>"]
    old_vocab, new_vocab = set(old["vocabulary"]), set(codec["vocabulary"])
    assert len(old_vocab & new_vocab) == 27
    assert old_vocab - new_vocab == {json.dumps("legal-counted-compact-content/v1")}
    assert new_vocab - old_vocab == {json.dumps("legal-counted-threshold-content/v2")}
    assert codec["vocabulary"][3:] == sorted(new_vocab-set(codec["vocabulary"][:3]))
    assert [codec["pad_id"], codec["bos_id"], codec["eos_id"]] == [0, 1, 2]
    assert codec["max_sequence_tokens"] == 512
    assert codec["checkpoint_compatibility_verified"] is False
    assert codec["numerical_head_compatible"] is False
    assert language["codec_sha256"] == sha(wire(codec))
    assert language["codec_sha256"] != legacy.counted_frame_token_codec_sha256(old)


def test_codec_factory_and_hash_return_detached_exact_metadata(language):
    offered = subject.build_counted_threshold_token_codec_v2()
    offered["vocabulary"].append("offered-change")
    assert subject.build_counted_threshold_token_codec_v2() == language["codec"]
    with pytest.raises(ValueError):
        subject.counted_threshold_token_codec_sha256(offered)


@pytest.mark.parametrize("index,maximum,expected_count", [(0, 1, 117), (1, 2, 195), (2, 3, 293)],
    ids=["maximum_one", "maximum_two", "maximum_three"])
def test_codec_complete_roundtrip_replays_real_typed_factory(language, index, maximum, expected_count):
    case = language["cases"][index]
    encoding, decoding = case["encoding"], case["decoding"]
    original = factory.prepare_counted_threshold_v2(case["request_raw"],
        expected_request_sha256=sha(case["request_raw"]))
    ids = encoding["target_ids"]
    assert len(ids) == expected_count and encoding["total_token_count"] == expected_count
    assert ids[0] == 1 and ids[-1] == 2 and all(type(i) is int and 3 <= i < 28 for i in ids[1:-1])
    assert encoding["prediction"]["typed_expression"] == original["typed_expression"]
    assert decoding["prediction"]["typed_expression"] == original["typed_expression"]
    assert encoding["counts"] == decoding["counts"] == original["counts"]
    assert encoding["prediction"]["maximum"] == decoding["prediction"]["maximum"] == maximum
    assert decoding["generated_ids"] == ids
    assert decoding["canonical_content_raw_utf8"] == encoding["canonical_content_raw_utf8"]
    raw = encoding["canonical_content_raw_utf8"].encode()
    assert sha(raw) == encoding["content_sha256"] == decoding["content_sha256"]
    assert encoding["context_sha256"] == decoding["context_sha256"] == language["context_sha256"]
    assert len(language["context_raw"]) == 483
    assert encoding["codec_sha256"] == decoding["codec_sha256"] == language["codec_sha256"]
    for report in (encoding, decoding):
        no_authority(report)
        no_authority(report["prediction"])
    assert decoding["prediction"]["source_binding"] is None


@pytest.mark.parametrize("index", [0, 1, 2], ids=["four_binders", "five_binders", "six_binders"])
def test_codec_compact_tree_and_independent_lexemes_preserve_ordered_typed_structure(language, index):
    case = language["cases"][index]
    maximum = case["maximum"]
    encoding = case["encoding"]
    raw = encoding["canonical_content_raw_utf8"].encode()
    content = json.loads(raw)
    assert set(content) == {"schema", "tree"}
    assert content["schema"] == "legal-counted-threshold-content/v2"
    assert wire(content) == raw
    tree = content["tree"]
    for level, sort in enumerate(["EventFrame", "TimeFrame"]+["Object"]*(maximum+1)):
        assert tree[:3] == ["forall", level, sort]
        tree = tree[3]
    assert tree[0] == "implies"
    physical = list(compact_nodes(content["tree"]))
    assert len(physical) == encoding["counts"]["nodes"]
    members = [node for node in physical if node[0] == "predicate"]
    assert members == [["predicate", 0, [["variable", level], ["variable", 0], ["variable", 1]]]
                       for level in range(2, maximum+3)]
    equalities = [node for node in physical if node[0] == "equality"]
    assert equalities == [["equality", ["variable", left], ["variable", right]]
                         for left, right in itertools.combinations(range(2, maximum+3), 2)]
    lexical = lexical_reference(raw)
    expected = [1]+[language["codec"]["vocabulary"].index(token) for token in lexical]+[2]
    assert encoding["target_ids"] == expected
    assert encoding["lexical_token_count"] == len(lexical) == len(expected)-2


def test_codec_original_request_whitespace_is_independently_committed(language):
    request = language["cases"][1]["request"]
    raw = (json.dumps(request, ensure_ascii=False, indent=2)+"\n").encode()
    report = subject.encode_counted_threshold_tokens_v2(raw, expected_request_sha256=sha(raw),
        codec=language["codec"], expected_codec_sha256=language["codec_sha256"])
    assert report["target_ids"] == language["cases"][1]["encoding"]["target_ids"]
    assert report["prediction"]["request_raw_utf8"] == raw.decode()
    assert report["prediction"]["request_sha256"] == sha(raw)
    assert sha(raw) != sha(wire(request))


def test_codec_context_transport_pin_is_distinct_from_common_canonical_identity(language):
    context = json.loads(language["context_raw"])
    raw = (json.dumps(context, ensure_ascii=False, indent=2)+"\n").encode()
    assert raw != language["context_raw"] and sha(raw) != language["context_sha256"]
    ids = language["cases"][1]["encoding"]["target_ids"]
    report = decode(language, ids, context_raw=raw, expected_context_sha256=sha(raw))
    inspected = prefix(language, [1], context_raw=raw, expected_context_sha256=sha(raw))
    for observed in (report, inspected):
        assert observed["context_raw_sha256"] == sha(raw)
        assert observed["context_sha256"] == language["context_sha256"]
        assert observed["permitted_inference_context_verified"] is False


def test_codec_every_prefix_and_all_twenty_eight_next_edges_match_union_oracle(language, all_states):
    assert all_states and len(all_states) <= sum(len(case["encoding"]["target_ids"])+1 for case in language["cases"])
    branching, terminal = 0, 0
    for state in all_states:
        ids, report = state["prefix_ids"], state["report"]
        matches, expected = oracle(language, ids)
        assert matches and report["offered_ids"] == ids
        assert report["allowed_token_ids"] == expected == sorted(set(expected))
        assert report["matching_completion_count"] == len(matches)
        assert report["admissible_content_count"] == 3 and report["profile_is_singleton"] is False
        assert report["remaining_token_slots"] == 512-len(ids)
        remaining = [len(case["encoding"]["target_ids"])-len(ids) for case in matches]
        assert report["completion_tokens_remaining_min"] == min(remaining)
        assert report["completion_tokens_remaining_max"] == max(remaining)
        for token_id in range(28):
            possible = any(case["encoding"]["target_ids"][:len(ids)+1] == ids+[token_id]
                           for case in language["cases"])
            assert (token_id in report["allowed_token_ids"]) is possible
        if expected:
            assert report["status"] == "prefix" and report["complete_candidate"] is None
        else:
            terminal += 1
            assert report["status"] == "complete" and report["complete_candidate"] is not None
            assert report["complete_candidate"]["generated_ids"] == ids
        branching += len(expected) > 1
        no_authority(report)
    assert terminal == 3 and branching >= 1


def test_codec_real_branch_choices_select_different_thresholds(language, all_states):
    vocabulary = language["codec"]["vocabulary"]
    branching = [state for state in all_states if len(state["report"]["allowed_token_ids"]) > 1]
    assert branching
    distinctions = set()
    for state in branching:
        ids = state["prefix_ids"]
        allowed = state["report"]["allowed_token_ids"]
        assert {vocabulary[index] for index in allowed} == {'"forall"', '"implies"'}
        choices = []
        for token_id in allowed:
            matched, _ = oracle(language, ids+[token_id])
            choices.append(frozenset(case["maximum"] for case in matched))
            observed = prefix(language, ids+[token_id])
            assert observed["status"] == "prefix" and observed["matching_completion_count"] == len(matched)
            for case in matched:
                assert decode(language, case["encoding"]["target_ids"])["prediction"]["maximum"] == case["maximum"]
        assert set.union(*(set(choice) for choice in choices)) <= {1, 2, 3}
        assert choices[0].isdisjoint(choices[1])
        distinctions.add(frozenset(choices))
    assert frozenset((frozenset((1,)), frozenset((2, 3)))) in distinctions
    assert frozenset((frozenset((2,)), frozenset((3,)))) in distinctions


@pytest.mark.parametrize("kind", ["empty", "bos", "complete_one", "complete_two", "complete_three"],
    ids=["empty", "bos", "complete_one", "complete_two", "complete_three"])
def test_codec_prefix_framing_is_explicit_and_never_repairs_offered_ids(language, kind):
    ids = [] if kind == "empty" else [1] if kind == "bos" else list(language["cases"][
        {"complete_one":0,"complete_two":1,"complete_three":2}[kind]]["encoding"]["target_ids"])
    original = list(ids)
    report = prefix(language, ids)
    assert report["offered_ids"] == ids == original
    if kind == "empty": assert report["allowed_token_ids"] == [1]
    if kind.startswith("complete"):
        assert report["status"] == "complete" and report["allowed_token_ids"] == []
    else: assert report["status"] == "prefix"


@pytest.mark.parametrize("damage", ["negative", "above_vocab", "missing_bos", "pad", "second_bos", "early_eos", "after_terminal"],
    ids=["negative", "above_vocab", "missing_bos", "pad", "second_bos", "early_eos", "after_terminal"])
def test_codec_bounded_dead_prefixes_are_preserved_rejected_data(language, damage):
    complete = language["cases"][0]["encoding"]["target_ids"]
    if damage == "negative": ids = [1, -1]
    elif damage == "above_vocab": ids = [1, 28]
    elif damage == "missing_bos": ids = complete[1:5]
    elif damage == "pad": ids = [1, 0]
    elif damage == "second_bos": ids = [1, 1]
    elif damage == "early_eos": ids = [1, 2]
    else: ids = list(complete)+[3]
    original = list(ids)
    report = prefix(language, ids)
    assert ids == original == report["offered_ids"]
    assert report["status"] == "rejected" and report["allowed_token_ids"] == []
    assert report["matching_completion_count"] == 0 and report["complete_candidate"] is None
    if damage in ("negative", "above_vocab"):
        assert report["reason"] == "out_of_vocabulary_id"
    no_authority(report)


@pytest.mark.parametrize("ids", [[True], [False], [1, 9223372036854775808], [1, -9223372036854775808], [[1]], (1,)],
    ids=["bool_true", "bool_false", "huge_positive", "huge_negative", "nested", "tuple"])
def test_codec_malformed_prefix_types_refuse_before_operation_owners(language, monkeypatch, ids):
    monkeypatch.setattr(subject, "_owners", lambda *args, **kwargs:pytest.fail("bad prefix reached syntax owners"))
    with pytest.raises(ValueError): prefix(language, ids)


def test_codec_full_budget_boundary_is_not_silently_truncated(language):
    offered = [1]*512
    report = prefix(language, offered)
    assert report["status"] == "rejected" and report["offered_ids"] == offered
    assert report["remaining_token_slots"] == 0
    with pytest.raises(ValueError): prefix(language, offered+[1])
    with pytest.raises(ValueError): decode(language, [1]+[3]*511+[2])


@pytest.mark.parametrize("damage", ["empty", "bos_only", "missing_eos", "missing_bos", "pad_inside", "bos_inside", "eos_inside", "bool"],
    ids=["empty", "bos_only", "missing_eos", "missing_bos", "pad_inside", "bos_inside", "eos_inside", "bool"])
def test_codec_incomplete_or_special_framing_refuses_before_operation_owners(language, monkeypatch, damage):
    ids = list(language["cases"][1]["encoding"]["target_ids"])
    if damage == "empty": ids = []
    elif damage == "bos_only": ids = [1]
    elif damage == "missing_eos": ids = ids[:-1]
    elif damage == "missing_bos": ids = ids[1:]
    elif damage == "pad_inside": ids[3] = 0
    elif damage == "bos_inside": ids[3] = 1
    elif damage == "eos_inside": ids[3] = 2
    else: ids[0] = True
    monkeypatch.setattr(subject, "_owners", lambda *args, **kwargs:pytest.fail("bad framing reached syntax owners"))
    with pytest.raises(ValueError): decode(language, ids)


@pytest.mark.parametrize("where", ["encode_request", "encode_codec", "decode_context", "decode_codec", "prefix_context"],
    ids=["encode_request", "encode_codec", "decode_context", "decode_codec", "prefix_context"])
def test_codec_wrong_independent_commitments_precede_operation_owners(language, monkeypatch, where):
    monkeypatch.setattr(subject, "_owners", lambda *args, **kwargs:pytest.fail("wrong pin reached syntax owners"))
    with pytest.raises(ValueError):
        if where.startswith("encode"):
            subject.encode_counted_threshold_tokens_v2(language["cases"][0]["request_raw"],
                expected_request_sha256="0"*64 if where == "encode_request" else sha(language["cases"][0]["request_raw"]),
                codec=language["codec"], expected_codec_sha256="0"*64 if where == "encode_codec" else language["codec_sha256"])
        elif where == "decode_context": decode(language, language["cases"][0]["encoding"]["target_ids"], expected_context_sha256="0"*64)
        elif where == "decode_codec": decode(language, language["cases"][0]["encoding"]["target_ids"], expected_codec_sha256="0"*64)
        else: prefix(language, [1], expected_context_sha256="0"*64)


@pytest.mark.parametrize("damage", ["legacy", "profile", "schema", "boolean_pad", "duplicate_token", "vocab_order", "extra"],
    ids=["legacy", "profile", "schema", "boolean_pad", "duplicate_token", "vocab_order", "extra"])
def test_codec_rehashed_foreign_or_altered_codecs_remain_foreign(language, monkeypatch, damage):
    offered = deepcopy(language["codec"])
    if damage == "legacy": offered = legacy.build_counted_frame_token_codec_v1()
    elif damage == "profile": offered["profile"] = "authored-at-most-three-many-sorted-compact/v1"
    elif damage == "schema": offered["content_schema"] = "legal-counted-compact-content/v1"
    elif damage == "boolean_pad": offered["pad_id"] = False
    elif damage == "duplicate_token": offered["vocabulary"][3] = offered["vocabulary"][4]
    elif damage == "vocab_order": offered["vocabulary"][3:5] = reversed(offered["vocabulary"][3:5])
    else: offered["target_ids"] = language["cases"][0]["encoding"]["target_ids"]
    offered_sha = sha(wire(offered))
    monkeypatch.setattr(subject, "_owners", lambda *args, **kwargs:pytest.fail("foreign codec reached syntax owners"))
    with pytest.raises(ValueError): subject.counted_threshold_token_codec_sha256(offered)
    with pytest.raises(ValueError): prefix(language, [1], codec=offered, expected_codec_sha256=offered_sha)


@pytest.mark.parametrize("damage", ["maximum", "old_context", "roles", "frame"],
    ids=["maximum", "old_context", "roles", "frame"])
def test_codec_rehashed_context_cannot_leak_a_cap_or_change_roles(language, monkeypatch, damage):
    context = json.loads(language["context_raw"])
    if damage == "maximum": context["maximum"] = 2
    elif damage == "old_context": context = legacy._compact_context()
    elif damage == "roles": context["membership"]["argument_roles"] = ["event", "object", "time"]
    else: context["frame"]["policy"] = "cumulative"
    raw = wire(context)
    monkeypatch.setattr(subject, "_owners", lambda *args, **kwargs:pytest.fail("altered context reached syntax owners"))
    with pytest.raises(ValueError): prefix(language, [1], context_raw=raw, expected_context_sha256=sha(raw))
    with pytest.raises(ValueError): decode(language, language["cases"][0]["encoding"]["target_ids"], context_raw=raw, expected_context_sha256=sha(raw))


@pytest.mark.parametrize("maximum", [True, 0, 4], ids=["bool", "zero", "four"])
def test_codec_encoder_reuses_closed_authored_request_contract(language, monkeypatch, maximum):
    request = deepcopy(language["cases"][0]["request"])
    request["maximum"] = maximum
    raw = wire(request)
    monkeypatch.setattr(subject, "_owners", lambda *args, **kwargs:pytest.fail("invalid declaration reached syntax owners"))
    with pytest.raises(ValueError):
        subject.encode_counted_threshold_tokens_v2(raw, expected_request_sha256=sha(raw),
            codec=language["codec"], expected_codec_sha256=language["codec_sha256"])


def test_codec_prefix_and_decoder_accept_no_expected_target_or_bound_parameters():
    common = {"context_raw", "expected_context_sha256", "codec", "expected_codec_sha256"}
    assert set(inspect.signature(subject.inspect_counted_threshold_prefix_v2).parameters) == common | {"prefix_ids"}
    assert set(inspect.signature(subject.decode_counted_threshold_tokens_v2).parameters) == common | {"generated_ids"}
    assert set(inspect.signature(subject.encode_counted_threshold_tokens_v2).parameters) == {
        "request_raw", "expected_request_sha256", "codec", "expected_codec_sha256"}


def test_codec_only_a_complete_prefix_delegates_to_genuine_public_decoder(language, monkeypatch):
    calls, actual = [], subject.decode_counted_threshold_tokens_v2
    def observed(*args, **kwargs):
        calls.append(deepcopy(args[0] if args else kwargs["generated_ids"]))
        return actual(*args, **kwargs)
    monkeypatch.setattr(subject, "decode_counted_threshold_tokens_v2", observed)
    assert prefix(language, [1])["complete_candidate"] is None
    assert calls == []
    ids = list(language["cases"][2]["encoding"]["target_ids"])
    report = prefix(language, ids)
    assert calls == [ids] and report["complete_candidate"]["prediction"]["maximum"] == 3


@pytest.mark.parametrize("target", ["prefix", "codec"], ids=["caller_prefix", "caller_codec"])
def test_codec_closing_fence_detects_original_caller_mutation(language, monkeypatch, target):
    ids = [1]
    codec = deepcopy(language["codec"])
    actual = factory.prepare_counted_threshold_v2
    changed = []
    def mutation(*args, **kwargs):
        report = actual(*args, **kwargs)
        if not changed:
            changed.append(True)
            if target == "prefix": ids.append(0)
            else: codec["pad_id"] = False
        return report
    monkeypatch.setattr(factory, "prepare_counted_threshold_v2", mutation)
    with pytest.raises(ValueError): prefix(language, ids, codec=codec)
    assert changed


@pytest.mark.parametrize("operation", ["prefix", "decode"], ids=["prefix_capture", "complete_id_capture"])
def test_codec_changed_ids_are_rechecked_after_capture_before_typed_work(language, monkeypatch, operation):
    offered = [1] if operation == "prefix" else list(language["cases"][0]["encoding"]["target_ids"])
    changed, actual = [], subject._watch
    def before_capture(base, original, observed):
        if original is offered:
            assert not changed
            changed.append(True)
            original[0] = True
        return actual(base, original, observed)
    monkeypatch.setattr(subject, "_watch", before_capture)
    monkeypatch.setattr(subject, "_owners", lambda *args, **kwargs:pytest.fail("captured bool alias reached typed work"))
    with pytest.raises(ValueError):
        if operation == "prefix": prefix(language, offered)
        else: decode(language, offered)
    assert changed and offered[0] is True


def test_codec_legacy_and_factory_sources_and_profiles_remain_unmodified(language):
    assert sha(Path(legacy.__file__).read_bytes()) == "df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13"
    assert sha(Path(factory.__file__).read_bytes()) == "9e3c4e42d8cfb5ed851461f6cd2562a71c7d5a2c2b8ccd5ab4fdbcf06e168024"
    assert legacy.COMPACT_CONTENT_SCHEMA == "legal-counted-compact-content/v1"
    old = legacy.build_counted_frame_token_codec_v1()
    assert old != language["codec"]
    with pytest.raises(ValueError):
        legacy.decode_counted_frame_tokens_v1(language["cases"][2]["encoding"]["target_ids"], language["context_raw"],
            expected_context_sha256=language["context_sha256"], codec=old,
            expected_codec_sha256=legacy.counted_frame_token_codec_sha256(old))


@pytest.mark.parametrize("damage", ["content_schema", "variable_role", "binder_sort", "equality_constructor",
    "equality_order", "binary_order", "duplicate_key"], ids=["content_schema", "variable_role", "binder_sort",
    "equality_constructor", "equality_order", "binary_order", "duplicate_key"])
def test_codec_well_framed_json_outside_the_three_forms_is_not_an_alias(language, damage):
    content = json.loads(language["cases"][1]["encoding"]["canonical_content_raw_utf8"])
    physical = list(compact_nodes(content["tree"]))
    if damage == "content_schema": content["schema"] = "Object"
    elif damage == "variable_role": next(node for node in physical if node[0] == "predicate")[2][0][1] = 0
    elif damage == "binder_sort": content["tree"][2] = "Object"
    elif damage == "equality_constructor": next(node for node in physical if node[0] == "equality")[0] = "predicate"
    elif damage == "equality_order":
        chosen = next(node for node in physical if node[0] == "equality")
        chosen[1], chosen[2] = chosen[2], chosen[1]
    elif damage == "binary_order":
        chosen = next(node for node in physical if node[0] == "and")
        chosen[1], chosen[2] = chosen[2], chosen[1]
    raw = wire(content)
    if damage == "duplicate_key":
        field = b'"schema":"legal-counted-threshold-content/v2"'
        assert raw.count(field) == 1
        raw = raw.replace(field, field+b','+field, 1)
    ids = [1]+[language["codec"]["vocabulary"].index(token) for token in lexical_reference(raw)]+[2]
    original = list(ids)
    with pytest.raises(ValueError): decode(language, ids)
    assert ids == original
    report = prefix(language, ids)
    assert report["status"] == "rejected" and report["complete_candidate"] is None


@pytest.mark.parametrize("boundary", ["self", "factory", "closing"], ids=["self", "factory", "closing"])
def test_codec_source_generations_are_fenced_before_return(language, monkeypatch, boundary):
    if boundary == "self":
        monkeypatch.setattr(subject, "_SELF_PIN", "0"*64)
        with pytest.raises(ValueError): subject.build_counted_threshold_token_codec_v2()
    elif boundary == "factory":
        monkeypatch.setattr(subject, "_FACTORY_SHA", "0"*64)
        with pytest.raises(ValueError): subject.counted_threshold_token_codec_sha256(language["codec"])
    else:
        actual = factory.prepare_counted_threshold_v2
        def changed_generation(*args, **kwargs):
            report = actual(*args, **kwargs)
            monkeypatch.setattr(subject, "_SELF_PIN", "0"*64)
            return report
        monkeypatch.setattr(factory, "prepare_counted_threshold_v2", changed_generation)
        with pytest.raises(ValueError): prefix(language, [1])


def test_codec_decoder_replays_all_three_original_public_factory_requests(language, monkeypatch):
    calls, actual = [], factory.prepare_counted_threshold_v2
    def observed(request_raw, **kwargs):
        request = json.loads(request_raw)
        assert kwargs["expected_request_sha256"] == sha(request_raw)
        calls.append(request["maximum"])
        return actual(request_raw, **kwargs)
    monkeypatch.setattr(factory, "prepare_counted_threshold_v2", observed)
    result = decode(language, language["cases"][1]["encoding"]["target_ids"])
    assert calls == [1, 2, 3]
    assert result["decoded_maximum"] == result["prediction"]["maximum"] == 2


def test_codec_panel_retains_three_roundtrips_and_exhaustive_prefix_edges(language, all_states, tmp_path):
    cases = [dict(maximum=case["maximum"], request_raw_utf8=case["request_raw"].decode(),
        request_sha256=sha(case["request_raw"]), encoding=case["encoding"], decoding=case["decoding"])
        for case in language["cases"]]
    states, branches, edge_checks = [], [], 0
    for state in all_states:
        ids, report = state["prefix_ids"], state["report"]
        matches, allowed = oracle(language, ids)
        assert report["allowed_token_ids"] == allowed
        for token_id in range(28):
            expected = any(case["encoding"]["target_ids"][:len(ids)+1] == ids+[token_id]
                           for case in language["cases"])
            assert (token_id in allowed) is expected
            edge_checks += 1
        states.append(dict(prefix_length=len(ids), prefix_ids_sha256=sha(wire(ids)),
            status=report["status"], allowed_token_ids=allowed,
            matching_completion_count=len(matches), surviving_maxima=[case["maximum"] for case in matches],
            completion_tokens_remaining_min=report["completion_tokens_remaining_min"],
            completion_tokens_remaining_max=report["completion_tokens_remaining_max"]))
        if len(allowed) > 1:
            branches.append(dict(prefix_ids=ids, allowed_token_ids=allowed,
                choices=[dict(token_id=token_id, completion_maxima=[case["maximum"]
                    for case in oracle(language, ids+[token_id])[0]]) for token_id in allowed]))
    assert branches and edge_checks == len(states)*28
    panel = dict(schema="legal-authored-counted-threshold-codec-prefix-panel/v2", codec=language["codec"],
        codec_sha256=language["codec_sha256"], context_raw_utf8=language["context_raw"].decode(),
        context_sha256=language["context_sha256"], cases=cases, prefix_states=states,
        prefix_state_count=len(states), edge_oracle_checks=edge_checks, branches=branches,
        branch_count=len(branches), admissible_content_count=3, profile_is_singleton=False,
        numerical_runtime_available=False, checkpoint_compatibility_verified=False,
        model_executed=False, training_executed=False, native_build_executed=False,
        source_dependence_established=False, training_mask=0, evaluation_gold_mask=0,
        authority={key:False for key in language["cases"][0]["encoding"]["authority"]})
    payload = wire(panel)
    assert len(payload) < 1048576
    target = tmp_path/"authored-threshold-codec-prefix-panel-v2.json"
    target.write_bytes(payload)
    assert target.read_bytes() == payload
