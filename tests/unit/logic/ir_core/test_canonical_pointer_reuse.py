"""Pure pointer reuse preserves canonical identity and validation semantics."""
from dataclasses import asdict

import pytest

from ipfs_datasets_py.logic.ir_core import canonical


def test_repeated_exact_pointer_decodes_once_and_is_immutable(monkeypatch):
    calls = []
    original = canonical._decode_pointer_segment

    def decode(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(canonical, "_decode_pointer_segment", decode)
    pointer = "/pointer-reuse-once~0~1"
    first = canonical._parse_pointer(pointer)
    second = canonical._parse_pointer(pointer)
    assert first == second == ("pointer-reuse-once~/",)
    assert type(first) is tuple
    assert calls == ["pointer-reuse-once~0~1"]


def test_pointer_reuse_is_bounded_and_eviction_reparses(monkeypatch):
    calls = []
    original = canonical._decode_pointer_segment

    def decode(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(canonical, "_decode_pointer_segment", decode)
    oldest = "/pointer-reuse-eviction-first"
    assert canonical._parse_pointer(oldest) == (oldest[1:],)
    for index in range(600):
        assert canonical._parse_pointer(f"/pointer-reuse-eviction-{index}") == (
            f"pointer-reuse-eviction-{index}",)
    assert canonical._parse_pointer(oldest) == (oldest[1:],)
    assert calls.count(oldest[1:]) == 2
    assert canonical._cached_pointer_parts.cache_info().currsize <= 512


def test_oversized_pointer_is_validated_without_retention(monkeypatch):
    calls = []
    original = canonical._decode_pointer_segment

    def decode(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(canonical, "_decode_pointer_segment", decode)
    pointer = "/" + "x" * 4096
    assert canonical._parse_pointer(pointer) == canonical._parse_pointer(pointer) == ("x" * 4096,)
    assert calls == ["x" * 4096, "x" * 4096]


def test_string_subclass_keeps_uncached_validation_behavior():
    class Pointer(str):
        __hash__ = None

        def startswith(self, prefix):
            self.observations += 1
            return super().startswith(prefix)

    pointer = Pointer("/subclass~1value")
    pointer.observations = 0
    assert canonical._parse_pointer(pointer) == canonical._parse_pointer(pointer) == ("subclass/value",)
    assert pointer.observations == 2


@pytest.mark.parametrize("pointer", [None, 1, [], {}])
def test_invalid_pointer_type_retains_specific_error(pointer):
    with pytest.raises(TypeError, match="collection paths must be strings"):
        canonical._parse_pointer(pointer)


@pytest.mark.parametrize("pointer", ["/bad~", "/bad~2", "/bad~01~x"])
def test_invalid_escape_is_rejected_on_every_call(pointer):
    for _ in range(2):
        with pytest.raises(canonical.CanonicalizationError, match="invalid JSON Pointer escape"):
            canonical._parse_pointer(pointer)


def test_rule_specificity_ambiguity_serialization_and_canonical_bytes_unchanged():
    schema = canonical.CollectionSchema({"/*/items": "ordered", "/selected/items": "set-like"})
    assert schema.to_dict() == {"/*/items": "ordered", "/selected/items": "set-like"}
    assert asdict(canonical.CollectionRule("/items", "multiset")) == {
        "pointer": "/items", "semantics": canonical.CollectionSemantics.MULTISET}
    payload = {"selected": {"items": ["b", "a", "b"]}, "other": {"items": ["b", "a", "b"]}}
    expected = b'{"other":{"items":["b","a","b"]},"selected":{"items":["a","b"]}}'
    assert canonical.canonical_json_bytes(payload, collection_schema=schema) == expected
    assert canonical.canonical_json_bytes(payload, collection_schema=schema) == expected
    ambiguous = canonical.CollectionSchema({"/*/items": "ordered", "/selected/*": "multiset"})
    for _ in range(2):
        with pytest.raises(canonical.CanonicalizationError, match="ambiguous collection rules"):
            canonical.canonical_json_bytes(payload, collection_schema=ambiguous)
