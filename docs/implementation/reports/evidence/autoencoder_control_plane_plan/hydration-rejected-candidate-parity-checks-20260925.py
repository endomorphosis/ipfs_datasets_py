"""Strict decoding parity and depth/mutation guards for primitive fast paths."""
from dataclasses import fields
import json
import math
import struct

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument, LogicIRView
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_snapshot as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_grammar_decoder import (
    LegalIRGrammarRejection, LegalIRGrammarValidation,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    _CachedLegalIRDocument, _CachedLegalIRTrainingTarget,
)


def legacy_decode(value, depth=0):
    """Pre-optimization recursive oracle, including its exact validation order."""
    if depth > 100:
        raise codec.TargetSnapshotError("target nesting limit exceeded")
    if value is None or type(value) in (str, bool, int, float):
        if type(value) is float and not math.isfinite(value):
            raise codec.TargetSnapshotError("nonfinite target number")
        return value
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise codec.TargetSnapshotError("invalid tagged value")
    kind = value["type"]
    if kind in {"mapping", "list", "tuple"}:
        if set(value) != {"type", "items"} or not isinstance(value["items"], list):
            raise codec.TargetSnapshotError("invalid collection encoding")
        if kind != "mapping":
            result = [legacy_decode(item, depth + 1) for item in value["items"]]
            return tuple(result) if kind == "tuple" else result
        result = {}
        for pair in value["items"]:
            if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str) or pair[0] in result:
                raise codec.TargetSnapshotError("invalid or duplicate mapping key")
            result[pair[0]] = legacy_decode(pair[1], depth + 1)
        return result
    if set(value) != {"type", "fields"}:
        raise codec.TargetSnapshotError("invalid object encoding")
    data = legacy_decode(value["fields"], depth + 1)
    if not isinstance(data, dict):
        raise codec.TargetSnapshotError("object fields must be a mapping")
    if kind == "rich_target":
        return codec.RichLegalIRTarget(data)
    cls = codec._types().get(kind)
    if cls is None or set(data) != {item.name for item in fields(cls)}:
        raise codec.TargetSnapshotError("unknown object or field schema")
    try:
        return cls(**data)
    except (ValueError, TypeError) as exc:
        raise codec.TargetSnapshotError("invalid object fields") from exc


def legacy_parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise codec.TargetSnapshotError("duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise codec.TargetSnapshotError(f"nonfinite JSON number: {value}")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise codec.TargetSnapshotError("invalid snapshot JSON") from exc


def outcome(function, value, *args):
    try:
        result = function(value, *args)
        return "value", codec._json(codec._encode(result))
    except Exception as exc:
        return "error", type(exc), str(exc)


def target_values():
    view = LogicIRView("deontic.ir", {"rules": [{"actor": "agency", "amount": -0.0}]},
                       metadata={"created_at": "2026-09-25T12:34:56Z", "tuple": (1.0, 2.0)})
    document = LegalIRDocument("doc", "The agency shall retain records.", "The agency shall retain records.",
        views={"deontic.ir": view}, frame_logic_triples=({"subject": "agency", "object": "records"},),
        metadata={"nested": {"value": 0.12345678912345678}})
    target = LegalIRTrainingTarget(("deontic_norms",), document, {"loss": .25},
                                   {"deontic_norms": {"loss": .125}}, {"deontic.ir": 1.0})
    reason = LegalIRGrammarRejection("fixture", "$.rules[0]", "deontic", "rule", "exact")
    candidate = {"family": "deontic", "rules": [{"modality": "invalid", "actor": "agency"}]}
    grammar = LegalIRGrammarValidation(False, "deontic", candidate, (reason,), ("chosen",), ("masked",))
    rich = codec.RichLegalIRTarget({**target.__dict__, "candidate_ir": candidate, "grammar_validation": grammar})
    cached_document = _CachedLegalIRDocument("timeout:" + "a" * 64, "doc", "timeout-v1")
    cached_target = _CachedLegalIRTrainingTarget(("deontic_norms",), cached_document, {"legal_ir_target_timeout_loss": 1.0})
    return [view, document, target, reason, grammar, rich, cached_document, cached_target]


@pytest.mark.parametrize("value", target_values())
def test_every_whitelisted_class_and_rich_target_keep_exact_tagged_bytes(value):
    raw = codec._json(codec._encode(value))
    restored = codec._decode(codec._parse(raw))
    previous = legacy_decode(legacy_parse(raw))
    assert type(restored) is type(previous) is type(value)
    assert codec._json(codec._encode(restored)) == codec._json(codec._encode(previous)) == raw


def test_mapping_order_tuple_list_types_and_exact_float_bits_are_preserved():
    leaves = [None, True, False, -2, 2**130, -0.0, 0.12345678912345678, "é"]
    value = {"z": leaves, "a": tuple(leaves), "empty": {"list": [], "tuple": (), "mapping": {}}}
    restored = codec._decode(codec._parse(codec._json(codec._encode(value))))
    assert list(restored) == ["z", "a", "empty"]
    assert type(restored["z"]) is list and type(restored["a"]) is tuple
    assert [type(item) for item in restored["z"]] == [type(item) for item in leaves]
    assert struct.pack(">d", restored["z"][5]) == struct.pack(">d", -0.0)
    assert struct.pack(">d", restored["a"][6]) == struct.pack(">d", leaves[6])


@pytest.mark.parametrize("raw", [
    b'{"a":1,"a":2}', b'{"a":1,"\\u0061":2}', b'{"outer":{"nested":1,"nested":2}}',
    b'{"type":"list","type":"tuple","items":[]}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"x":-Infinity}', b'{"x":1e999}', b'{"x":-1e999}', b'{"x":-0.0}',
    b'{"z":1,"a":[true,false,null]}', b'[1,2]', b'null', b'\xff', b'{',
])
def test_strict_json_parse_acceptance_and_errors_match_previous_codec(raw):
    assert outcome(codec._parse, raw) == outcome(legacy_parse, raw)


INVALID_TAGS = [
    [], (), {}, {"type": []}, {"type": "list"}, {"type": "tuple", "items": (), "extra": 1},
    {"type": "mapping", "items": {}}, {"type": "mapping", "items": [[1, 2]]},
    {"type": "mapping", "items": [["x", 1], ["x", 2]]},
    {"type": "mapping", "items": [("x", 1)]}, {"type": "mapping", "items": [["x"]]},
    {"type": "list", "items": [[]]}, {"type": "tuple", "items": [{}]},
    {"type": "arbitrary.module.Class", "fields": {"type": "mapping", "items": []}},
    {"type": "LegalIRDocument", "fields": {"type": "mapping", "items": [["extra", 1]]}},
    {"type": "LegalIRDocument", "fields": {"type": "list", "items": []}},
    {"type": "rich_target", "fields": {"type": "mapping", "items": [["_private", 1]]}},
    {"type": "rich_target", "fields": {"type": "mapping", "items": [["to_dict", 1]]}},
    {"type": "list", "items": [float("nan")]},
    {"type": "mapping", "items": [["x", float("inf")]]},
    {"type": "tuple", "items": [float("-inf")]},
]


@pytest.mark.parametrize("value", INVALID_TAGS)
def test_malformed_tags_collections_and_nonfinite_values_keep_rejection(value):
    assert outcome(codec._decode, value) == outcome(legacy_decode, value)


@pytest.mark.parametrize("kind", ["mapping", "list", "tuple"])
@pytest.mark.parametrize("leaf", [None, True, "text", 1, -0.0, float("inf"), [], {}])
@pytest.mark.parametrize("depth", [99, 100, 101])
def test_direct_depth_boundary_checks_scalar_leaves_and_validation_order(kind, leaf, depth):
    value = {"type": kind, "items": [["key", leaf]] if kind == "mapping" else [leaf]}
    assert outcome(codec._decode, value, depth) == outcome(legacy_decode, value, depth)


@pytest.mark.parametrize("kind", ["mapping", "list", "tuple"])
def test_empty_container_at_depth100_is_allowed_but_depth101_is_not(kind):
    value = {"type": kind, "items": []}
    assert outcome(codec._decode, value, 100)[0] == "value"
    assert outcome(codec._decode, value, 100) == outcome(legacy_decode, value, 100)
    assert outcome(codec._decode, value, 101) == outcome(legacy_decode, value, 101)
    assert outcome(codec._decode, value, 101)[0] == "error"


@pytest.mark.parametrize("depth", [100, 101])
def test_real_nested_json_obeys_tagged_depth_not_structural_array_depth(depth):
    value = "scalar"
    for _ in range(depth):
        value = {"type": "list", "items": [value]}
    parsed = codec._parse(codec._json(value))
    assert outcome(codec._decode, parsed) == outcome(legacy_decode, parsed)
    assert outcome(codec._decode, parsed)[0] == ("value" if depth == 100 else "error")


def test_mutable_hydration_never_aliases_input_or_independent_results():
    encoded = codec._encode(target_values()[5])
    before = codec._json(encoded)
    first, second = codec._decode(encoded), codec._decode(encoded)
    first.losses["new"] = 99.0
    first.document.metadata["nested"]["value"] = "changed"
    first.document.views["deontic.ir"].payload["rules"][0]["amount"] = 7.0
    first.candidate_ir["rules"].append({"new": True})
    first.grammar_validation.candidate_ir["rules"].append({"changed": True})
    assert codec._json(encoded) == before
    assert codec._json(codec._encode(second)) == before
    assert codec._json(codec._encode(codec._decode(encoded))) == before


def test_primitive_collection_leaves_do_not_dispatch_recursively(monkeypatch):
    original = codec._decode
    calls = []
    def tracked(value, depth=0):
        calls.append(value)
        return original(value, depth)
    monkeypatch.setattr(codec, "_decode", tracked)
    value = {"list": [1, None, True, "text", -0.0] * 10, "tuple": (False, 2.5, "x")}
    assert codec._decode(codec._encode(value)) == value
    assert len(calls) == 3
    assert all(type(item) is dict for item in calls)
