"""Compatibility against the pre-optimization snapshot and scalar wire rules.

The reference routines deliberately do not call the current wire implementation:
snapshot and scalar serialization are optimized together, so sharing that helper
would hide a regression in both paths. These tests exercise bounded synthetic
inputs, without invoking any evidence preparation or semantic admission owner.
"""
import hashlib
import json
import math
import random
from decimal import Decimal

import pytest

from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as norm


def _need(value, message):
    if not value:
        raise ValueError(message)


def _reference_wire(value, maximum):
    """Original correspondence wire algorithm, including its scalar guards."""
    remaining = 500000
    byte_budget = maximum

    def charge(count):
        nonlocal byte_budget
        byte_budget -= count
        _need(byte_budget >= 0, "complete JSON byte bound exceeded")

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        _need(remaining >= 0 and depth <= 96, "bounded ordinary JSON required")
        if type(item) is dict:
            charge(2 + max(0, len(item) - 1) + len(item))
            for key, child in item.items():
                _need(type(key) is str, "ordinary string JSON keys required")
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif type(item) is list:
            charge(2 + max(0, len(item) - 1))
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            _need("\x00" not in item and len(item) + 2 <= byte_budget,
                  "bounded UTF8 strings required")
            try:
                charge(len(json.dumps(item, ensure_ascii=False).encode("utf-8")))
            except UnicodeError as error:
                raise ValueError("ordinary UTF8 strings required") from error
        elif item is None or type(item) is bool:
            charge(4 if item is None or item is True else 5)
        elif type(item) is int:
            _need(-(1 << 63) < item < (1 << 63), "bounded JSON integer required")
            charge(len(str(item)))
        elif type(item) is float:
            _need(item == item and abs(item) != float("inf"), "finite JSON number required")
            charge(len(json.dumps(item)))
        else:
            raise ValueError("ordinary JSON values required")

    visit(value, 0)
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded ordinary UTF8 JSON required") from error
    _need(len(raw) <= maximum, "complete JSON byte bound exceeded")
    return raw


def _reference_snapshot(value, *, max_nodes=1_500_000):
    """Original snapshot traversal, scalar JSON round trip, and commitment."""
    _need(type(max_nodes) is int and 0 < max_nodes <= 4_000_000,
          "bounded positive integer snapshot node budget required")
    budget, nodes = norm.MAX_INPUT_BYTES, max_nodes
    digest = hashlib.sha256()

    def token(tag, raw):
        nonlocal budget
        budget -= len(raw) + 16
        _need(budget >= 0, "aggregate review input byte bound exceeded")
        digest.update(tag + str(len(raw)).encode() + b":" + raw)

    def visit(item, depth):
        nonlocal nodes
        nodes -= 1
        _need(nodes >= 0 and depth <= 96, "bounded review input structure required")
        if type(item) is dict:
            _need(len(item) <= nodes and all(type(key) is str for key in item),
                  "ordinary review mapping required")
            token(b"d", str(len(item)).encode())
            return {visit(key, depth + 1): visit(item[key], depth + 1) for key in sorted(item)}
        if type(item) is list:
            _need(len(item) <= nodes, "bounded review list required")
            token(b"l", str(len(item)).encode())
            return [visit(child, depth + 1) for child in item]
        if type(item) is bytes:
            _need(len(item) <= min(budget, 32 * 1024**2), "bounded exact review bytes required")
            token(b"b", item)
            return item
        raw = _reference_wire(item, min(budget, norm.MAX_INPUT_BYTES))
        token(b"j", raw)
        return json.loads(raw)

    detached = visit(value, 0)
    return detached, digest.hexdigest()


def _assert_typed_equal(actual, expected):
    assert type(actual) is type(expected)
    if type(expected) is dict:
        assert list(actual) == list(expected)
        for key in expected:
            _assert_typed_equal(actual[key], expected[key])
    elif type(expected) is list:
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            _assert_typed_equal(left, right)
    elif type(expected) is float:
        assert actual.hex() == expected.hex()  # Includes the sign of zero.
    else:
        assert actual == expected


def _assert_snapshot_compatible(value, **kwargs):
    try:
        expected, commitment = _reference_snapshot(value, **kwargs)
    except ValueError:
        with pytest.raises(ValueError):
            norm._snapshot(value, **kwargs)
        return False
    actual, observed = norm._snapshot(value, **kwargs)
    _assert_typed_equal(actual, expected)
    assert observed == commitment
    return True


SCALARS = [None, False, True, 0, 1, -1, -(1 << 63) + 1, (1 << 63) - 1,
           0.0, -0.0, 1.0, -1.25, 5e-324, 1.7976931348623157e308,
           "", "quote\" slash\\ control\x01\t\r\n\b\f", "Clérk 法 § 😀",
           "e\u0301", "é", "\u2028\u2029"]


@pytest.mark.parametrize("value", SCALARS)
def test_scalar_bytes_and_snapshot_match_reference_at_exact_byte_boundaries(value, monkeypatch):
    raw = _reference_wire(value, 1024)
    for maximum in (0, len(raw) - 1, len(raw), len(raw) + 1):
        if maximum < len(raw):
            with pytest.raises(ValueError):
                _reference_wire(value, maximum)
            with pytest.raises(ValueError):
                norm.correspondence_owner._wire(value, maximum)
        else:
            assert norm.correspondence_owner._wire(value, maximum) == raw
    for maximum in (len(raw) - 1, len(raw), len(raw) + 15, len(raw) + 16):
        monkeypatch.setattr(norm, "MAX_INPUT_BYTES", maximum)
        assert _assert_snapshot_compatible(value) is (maximum >= len(raw) + 16)


def _generated_tree(seed):
    rng = random.Random(seed)
    leaves = SCALARS + [b"", b"\x00\xff\x80", b"source\nbytes"]

    def build(depth):
        if depth == 0 or rng.randrange(3) == 0:
            return rng.choice(leaves)
        count = rng.randrange(5)
        if rng.randrange(2):
            return [build(depth - 1) for _ in range(count)]
        # Deliberately reverse insertion order; canonical order is lexical.
        return {f"項目-{i}": build(depth - 1) for i in reversed(range(count))}

    return build(5)


@pytest.mark.parametrize("seed", range(32))
def test_deterministically_generated_trees_preserve_typed_values_and_commitment(seed):
    assert _assert_snapshot_compatible(_generated_tree(seed))


def test_typed_tokens_have_independent_known_encoding():
    value = [False, 0, 0.0, b"0", "0"]
    expected_stream = b'l1:5j5:falsej1:0j3:0.0b1:0j3:"0"'
    assert norm._snapshot(value)[1] == hashlib.sha256(expected_stream).hexdigest()
    commitments = {norm._snapshot(item)[1] for item in (False, 0, 0.0, True, 1, 1.0, -0.0)}
    assert len(commitments) == 7
    assert math.copysign(1.0, norm._snapshot(-0.0)[0]) == -1.0


def test_mapping_order_is_canonical_but_unicode_is_not_normalized():
    left = {"z": 0, "é": 1, "a": 2}
    right = dict(reversed(list(left.items())))
    assert _assert_snapshot_compatible(left)
    assert norm._snapshot(left) == norm._snapshot(right)
    assert list(norm._snapshot(left)[0]) == sorted(left)
    assert norm._snapshot("e\u0301")[1] != norm._snapshot("é")[1]


@pytest.mark.parametrize("value", [[], {}, {"é": [None, True, 0, -0.0, "quoted\""]},
                                 [{"z": 3, "a": [False, 1.5]}]])
def test_direct_wire_compound_values_keep_the_original_encoding_and_byte_limits(value):
    raw = _reference_wire(value, 4096)
    assert norm.correspondence_owner._wire(value, len(raw)) == raw
    with pytest.raises(ValueError):
        _reference_wire(value, len(raw) - 1)
    with pytest.raises(ValueError):
        norm.correspondence_owner._wire(value, len(raw) - 1)


@pytest.mark.parametrize("value", [b"", b"\x00\xff"])
def test_bytes_remain_snapshot_only_not_json_wire_scalars(value):
    assert _assert_snapshot_compatible(value)
    with pytest.raises(ValueError):
        _reference_wire(value, 4096)
    with pytest.raises(ValueError):
        norm.correspondence_owner._wire(value, 4096)


def test_repeated_aliases_detach_each_occurrence_and_bind_each_mutation():
    shared = {"payload": [True, 1, 1.0, b"\x00\xff"], "nested": {"value": "é"}}
    original = [shared, shared]
    assert _assert_snapshot_compatible(original)
    detached, commitment = norm._snapshot(original)
    assert detached[0] is not original[0]
    assert detached[0] is not detached[1]
    assert detached[0]["payload"] is not detached[1]["payload"]
    assert detached[0]["nested"] is not detached[1]["nested"]
    detached[0]["payload"][0] = 1
    assert original[0]["payload"][0] is True
    assert detached[1]["payload"][0] is True
    assert norm._snapshot(detached)[1] != commitment
    assert norm._snapshot(original)[1] == commitment
    original[0]["nested"]["value"] = "changed"
    assert detached[0]["nested"]["value"] == "é"
    assert norm._snapshot(original)[1] != commitment


class _Int(int):
    pass


class _Float(float):
    pass


class _String(str):
    pass


class _Bytes(bytes):
    pass


class _List(list):
    pass


class _Dict(dict):
    pass


@pytest.mark.parametrize("value", [
    -(1 << 63), 1 << 63, 10**1000, float("nan"), float("inf"), -float("inf"),
    "\x00", "a\x00b", "\ud800", "\udfff", "\ud800\udfff",
    _Int(1), _Float(1.0), _String("a"), _Bytes(b"a"), _List([1]), _Dict(a=1),
    (), (1,), {1}, frozenset({1}), bytearray(b"a"), memoryview(b"a"),
    1j, Decimal("1"), object(), range(1),
    {1: "value"}, {None: "value"}, {True: "value"}, {_String("a"): "value"},
])
def test_unsupported_values_and_exact_type_subclasses_remain_rejected(value):
    assert _assert_snapshot_compatible(value) is False
    # Exercise scalar early dispatch separately, including unsupported containers.
    with pytest.raises(ValueError):
        _reference_wire(value, 4096)
    with pytest.raises(ValueError):
        norm.correspondence_owner._wire(value, 4096)


@pytest.mark.parametrize("container", ["list", "dict"])
def test_cycles_fail_boundedly(container):
    value = [] if container == "list" else {}
    if container == "list":
        value.append(value)
    else:
        value["self"] = value
    assert _assert_snapshot_compatible(value) is False


@pytest.mark.parametrize("depth,accepted", [(95, True), (96, True), (97, False)])
def test_depth_boundary_is_unchanged(depth, accepted):
    value = None
    for _ in range(depth):
        value = [value]
    assert _assert_snapshot_compatible(value) is accepted


@pytest.mark.parametrize("value,required_nodes", [([], 1), ({}, 1), (None, 1),
                                                 ([None], 2), ({"a": None}, 3),
                                                 ([[True, None], [False, None]], 7)])
def test_node_boundary_counts_mapping_keys_and_repeated_occurrences(value, required_nodes):
    assert _assert_snapshot_compatible(value, max_nodes=required_nodes)
    assert _assert_snapshot_compatible(value, max_nodes=required_nodes + 1)
    if required_nodes > 1:
        assert _assert_snapshot_compatible(value, max_nodes=required_nodes - 1) is False


@pytest.mark.parametrize("maximum", [None, True, False, "1", 1.0, _Int(1), 0, -1, 4_000_001])
def test_node_profile_rejects_nonexact_or_out_of_range_budget(maximum):
    assert _assert_snapshot_compatible([], max_nodes=maximum) is False


@pytest.mark.parametrize("value,charge", [(b"", 16), (b"\x00\xff", 18),
                                        ([], 17), ({}, 17), ([b"x", b"y"], 51),
                                        ({"é": b"x"}, 54)])
def test_aggregate_budget_includes_type_tokens_utf8_and_each_occurrence(value, charge, monkeypatch):
    for maximum in (charge - 1, charge, charge + 1):
        monkeypatch.setattr(norm, "MAX_INPUT_BYTES", maximum)
        assert _assert_snapshot_compatible(value) is (maximum >= charge)


def test_per_body_bytes_bound_rejects_before_hashing_even_with_larger_aggregate_budget():
    # One rejected allocation avoids processing a large synthetic evidence tree.
    oversized = b"x" * (32 * 1024**2 + 1)
    assert len(oversized) < norm.MAX_INPUT_BYTES
    assert _assert_snapshot_compatible(oversized) is False


def test_shared_aliases_are_not_deduplicated_for_node_or_byte_accounting(monkeypatch):
    shared = [b"x"]
    value = [shared, shared]
    assert _assert_snapshot_compatible(value, max_nodes=5)
    assert _assert_snapshot_compatible(value, max_nodes=4) is False
    # Root list 17 + twice (list 17 + bytes 17), regardless of Python identity.
    monkeypatch.setattr(norm, "MAX_INPUT_BYTES", 85)
    assert _assert_snapshot_compatible(value)
    monkeypatch.setattr(norm, "MAX_INPUT_BYTES", 84)
    assert _assert_snapshot_compatible(value) is False
