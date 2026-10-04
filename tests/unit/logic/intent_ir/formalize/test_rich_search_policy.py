"""Independent grammar-policy checks; no neural inference is mocked or claimed."""
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar as grammar
from ipfs_datasets_py.logic.intent_ir.formalize import rich_search_policy as api
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_paired_text import tokenize


def _tokens(text):
    return tuple(tokenize(text)) if text else ()


def _every_prefix(policy, tokens):
    for end in range(len(tokens) + 1):
        assert policy(tokens[:end]), (end, tokens[:end])
    assert policy(tokens, eos=True)


@pytest.mark.parametrize("direction", ["encode", "decode"])
@pytest.mark.parametrize("instruction", [
    "agent must inspect Cache.py.",
    "agent must not delete `Src/Cache-v2.py`.",
    "reviewer may compare API:Result_v2.",
    "operator should inspect src/cache.py.",
    "agent intends to inspect Cache.py.",
    "agent must inspect cache and reviewer may approve report.",
    "agent must inspect cache or reviewer may approve report.",
    "agent must inspect cache then reviewer may approve report.",
    "if Cache.py is Ready_State, agent must inspect Cache.py.",
    "if Cache.py is not Empty, agent must not delete Cache.py.",
])
def test_all_prefixes_of_complete_frozen_grammar_examples_survive(direction, instruction):
    ast = grammar.parse_instruction(instruction, normalized_inverse=True)
    text = grammar.ast_to_sequence(ast) if direction == "encode" else grammar.ast_to_text(ast)
    _every_prefix(api.RichPrefixConstraint(direction), _tokens(text))


@pytest.mark.parametrize("sequence", [
    "<action> inspect <actor> agent <object> cache <modality> required",
    "<actor> agent <object> cache <action> inspect <modality> required",
    "<actor> <action> inspect <object> cache <modality> required",
    "<actor> agent <action> inspect <object> cache <modality> compulsory",
    "<if> cache <property> empty <polarity> maybe <body> <actor> agent",
    "<and> <or> <actor> agent",
    "<if> cache <property> ready <polarity> positive <body> <if> cache",
    "<actor> agent <action> inspect <object> cache <modality> required <next>",
])
def test_impossible_marker_order_and_nested_constructs_are_pruned(sequence):
    policy = api.RichPrefixConstraint("encode")
    assert not policy(_tokens(sequence))
    assert not policy(_tokens(sequence), eos=True)


@pytest.mark.parametrize("prefix", [
    "", "<actor>", "<actor> agent", "<actor> agent <action> inspect",
    "<actor> agent <action> inspect <object> cache <modality>",
    "<and> <actor> agent <action> inspect <object> cache <modality> required",
    "<if> cache <property> ready <polarity> positive <body>",
])
def test_open_productions_cannot_end(prefix):
    policy = api.RichPrefixConstraint("encode")
    assert policy(_tokens(prefix))
    assert not policy(_tokens(prefix), eos=True)


def test_modal_prefix_ambiguity_keeps_required_prohibited_and_intended_paths():
    policy = api.RichPrefixConstraint("decode")
    for text in ("agent must", "agent must not", "agent intends", "agent intends to"):
        assert policy(_tokens(text))
        assert not policy(_tokens(text), eos=True)
    for text in ("agent must inspect cache.", "agent must not inspect cache.",
                 "agent intends to inspect cache."):
        _every_prefix(policy, _tokens(text))


def test_unclosed_backticks_are_possible_but_cannot_cross_slot_boundary():
    policy = api.RichPrefixConstraint("encode")
    prefix = _tokens("<actor> agent <action> inspect <object> `Src/Cache.py")
    assert policy(prefix)
    assert not policy(prefix + ("<modality>", "required"))
    _every_prefix(policy, prefix + ("`", "<modality>", "required"))


def test_full_ast_slot_bounds_are_enforced_before_eos():
    policy = api.RichPrefixConstraint("encode")
    template = "<actor> {actor} <action> inspect <object> {object} <modality> required"
    for actor, obj in (("one two three four five", "cache"), ("agent", " ".join(["cache"] * 17)),
                       ("agent", "x" * 161)):
        assert not policy(_tokens(template.format(actor=actor, object=obj)), eos=True)
    complete = template.format(actor="one two three four", object="x" * 160)
    _every_prefix(policy, _tokens(complete))


def test_no_source_parser_runs_for_generated_prefixes_or_encode_completion(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("source parser cannot supply generated prefix decisions")

    monkeypatch.setattr(grammar, "parse_instruction", forbidden)
    encode = api.RichPrefixConstraint("encode")
    _every_prefix(encode, _tokens("<actor> agent <action> inspect <object> Cache.py <modality> required"))
    decode = api.RichPrefixConstraint("decode")
    tokens = _tokens("agent must inspect Cache.py.")
    for end in range(len(tokens) + 1):
        assert decode(tokens[:end])


def test_inverse_eos_parser_receives_only_generated_text(monkeypatch):
    calls = []
    original = grammar.parse_instruction

    def observed(text, **kwargs):
        calls.append((text, kwargs))
        return original(text, **kwargs)

    monkeypatch.setattr(grammar, "parse_instruction", observed)
    policy = api.RichPrefixConstraint("decode")
    _every_prefix(policy, _tokens("if Cache.py is not Empty, agent must not delete Cache.py."))
    assert calls == [("if Cache.py is not Empty, agent must not delete Cache.py.",
                      {"normalized_inverse": True})]


@pytest.mark.parametrize("text", [
    "agent must inspect cache unless approved.",
    "agent must inspect cache and delete cache.",
    "if cache is ready, agent must inspect cache and reviewer may approve report.",
    "they must inspect cache.",
    "every agent must inspect cache.",
])
def test_inverse_completion_cannot_admit_unsupported_scope(text):
    assert not api.RichPrefixConstraint("decode")(_tokens(text), eos=True)


def test_policy_rejects_protocol_tokens_unicode_and_oversized_prefixes():
    policy = api.RichPrefixConstraint("encode")
    for tokens in (("<bos>",), ("<actor>", "élève"), tuple(["word"] * 161),
                   ["<actor>"], ("<actor>", 1)):
        assert not policy(tokens)
    assert not policy(("<actor>",), eos=1)
    with pytest.raises(ValueError):
        api.RichPrefixConstraint("unknown")


def test_policy_identity_pins_the_exact_source():
    identity = api.policy_identity()
    assert identity["policy_id"] == api.POLICY_ID
    assert identity["policy_sha256"] == hashlib.sha256(Path(api.__file__).read_bytes()).hexdigest()
