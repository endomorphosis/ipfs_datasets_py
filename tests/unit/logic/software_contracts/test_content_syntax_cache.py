"""Syntax memoization never substitutes for verification of actual bytes."""

import pytest

from ipfs_datasets_py.logic.software_contracts import content


def test_successful_syntax_is_reused_only_for_exact_codec_and_profile(monkeypatch):
    content._validate_canonical_cid_syntax.cache_clear()
    raw = content.cid_for_bytes(b"public source")
    assert content.validate_cid(raw, codecs={"raw"}) == raw
    before = content._validate_canonical_cid_syntax.cache_info()
    assert content.validate_cid(raw, codecs={"raw"}) == raw
    assert content._validate_canonical_cid_syntax.cache_info().hits == before.hits + 1
    with pytest.raises(content.ContentIdentityError):
        content.validate_cid(raw, codecs={"dag-json"})
    monkeypatch.setattr(content, "CID_VERSION", 0)
    with pytest.raises(content.ContentIdentityError):
        content.validate_cid(raw, codecs={"raw"})
    assert content._validate_canonical_cid_syntax.cache_info().maxsize == 32768


@pytest.mark.parametrize("value", [None, [], {}, 12, b"abc", "", "NOT-CANONICAL"])
def test_invalid_types_and_strings_remain_rejected_outside_success_cache(value):
    before = content._validate_canonical_cid_syntax.cache_info().currsize
    with pytest.raises(content.ContentIdentityError):
        content.validate_cid(value)
    assert content._validate_canonical_cid_syntax.cache_info().currsize == before


def test_cached_cid_cannot_validate_changed_source_or_structured_root():
    source = b"before"
    source_cid = content.cid_for_bytes(source)
    content.validate_cid(source_cid, codecs={"raw"})
    assert content.decode_and_recompute_source(source_cid, source) == source_cid
    with pytest.raises(content.ContentIdentityError, match="does not match"):
        content.decode_and_recompute_source(source_cid, b"after")
    root = {"schema": "test-root@1", "sources": [source_cid], "completion_authority": False}
    root_cid = content.cid_for_structured(root)
    content.validate_cid(root_cid, codecs={"dag-json"})
    assert content.decode_and_recompute_structured(root_cid, root) == root_cid
    with pytest.raises(content.ContentIdentityError, match="does not match"):
        content.decode_and_recompute_structured(root_cid, {**root, "completion_authority": True})


def test_unhashable_string_subclass_retains_uncached_validation_contract():
    class UnhashableString(str):
        __hash__ = None

    raw = content.cid_for_bytes(b"subclass")
    value = UnhashableString(raw)
    before = content._validate_canonical_cid_syntax.cache_info()
    assert content.validate_cid(value) is value
    assert content._validate_canonical_cid_syntax.cache_info() == before
