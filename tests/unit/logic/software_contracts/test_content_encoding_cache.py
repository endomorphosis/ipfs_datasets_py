"""CID encoding reuse never caches source bytes or content verification."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from multiformats import CID, multihash

from ipfs_datasets_py.logic.software_contracts import content


def native_cid(raw, *, codec, base=None, version=None, hash_name=None):
    return str(CID(base if base is not None else content.CID_BASE,
                   version if version is not None else content.CID_VERSION,
                   codec, multihash.digest(raw, hash_name or content.MULTIHASH_TYPE)))


@pytest.fixture(autouse=True)
def clear_encoding_cache():
    content._encode_cid_digest.cache_clear()
    yield
    content._encode_cid_digest.cache_clear()


@pytest.mark.parametrize("raw", [b"", b"hello", b"\x00\xff", "λ café".encode(), bytes(range(256))])
def test_raw_cid_cache_miss_and_hit_match_real_native_encoding(raw):
    expected = native_cid(raw, codec="raw")
    assert content.cid_for_bytes(raw) == expected
    before = content._encode_cid_digest.cache_info()
    assert content.cid_for_bytes(raw) == expected
    after = content._encode_cid_digest.cache_info()
    assert after.hits == before.hits + 1
    assert after.maxsize == 32768


@pytest.mark.parametrize("obj", [None, True, 1, "λ café", [1, None, ""], {"z": [1, {"café": True}], "a": "λ"}])
def test_structured_cid_cache_miss_and_hit_match_real_native_encoding(obj):
    expected = native_cid(content.canonical_dag_json_bytes(obj), codec="dag-json")
    assert content.cid_for_structured(obj) == expected
    before = content._encode_cid_digest.cache_info()
    assert content.cid_for_structured(obj) == expected
    assert content._encode_cid_digest.cache_info().hits == before.hits + 1


def test_same_bytes_keep_raw_and_structured_codec_domains_separate():
    obj = {"sources": [], "completion_authority": False}
    raw = content.canonical_dag_json_bytes(obj)
    source = content.cid_for_bytes(raw)
    structured = content.cid_for_structured(obj)
    assert source != structured
    assert source == native_cid(raw, codec="raw")
    assert structured == native_cid(raw, codec="dag-json")
    assert content._encode_cid_digest.cache_info().currsize == 2


def test_every_hit_and_read_recomputes_actual_hash(monkeypatch):
    original = multihash.digest
    calls = []

    def counted(raw, name, *args, **kwargs):
        calls.append((raw, name))
        return original(raw, name, *args, **kwargs)

    monkeypatch.setattr(multihash, "digest", counted)
    raw = b"freshly hashed every time"
    source = content.cid_for_bytes(raw)
    assert content.cid_for_bytes(raw) == source
    assert content.decode_and_recompute_source(source, raw) == source
    obj = {"sources": [source], "accepted": False}
    structured = content.cid_for_structured(obj)
    assert content.cid_for_structured(obj) == structured
    assert content.decode_and_recompute_structured(structured, obj) == structured
    assert [raw for raw, _ in calls] == [raw] * 3 + [content.canonical_dag_json_bytes(obj)] * 3
    assert all(name == content.MULTIHASH_TYPE for _, name in calls)
    assert content._encode_cid_digest.cache_info().hits >= 4


def test_warm_encoding_and_syntax_never_accept_changed_source_or_nested_state():
    source = content.cid_for_bytes(b"before")
    assert content.decode_and_recompute_source(source, b"before") == source
    with pytest.raises(content.ContentIdentityError, match="does not match"):
        content.decode_and_recompute_source(source, b"after")
    obj = {"program": {"sources": [source], "completed": False}}
    structured = content.cid_for_structured(obj)
    assert content.decode_and_recompute_structured(structured, obj) == structured
    obj["program"]["completed"] = True
    with pytest.raises(content.ContentIdentityError, match="does not match"):
        content.decode_and_recompute_structured(structured, obj)


def test_actual_bundle_block_verification_still_rejects_corruption():
    from ipfs_datasets_py.logic.software_contracts.semantic_state.models import verify_block_bytes
    raw = b"native block"
    source = content.cid_for_bytes(raw)
    assert verify_block_bytes(source, raw) == source
    with pytest.raises(ValueError):
        verify_block_bytes(source, b"different block")
    payload = {"schema": "native-fixture@1", "accepted": False}
    structured = content.cid_for_structured(payload)
    assert verify_block_bytes(structured, content.canonical_dag_json_bytes(payload)) == structured
    with pytest.raises(ValueError):
        verify_block_bytes(structured, content.canonical_dag_json_bytes({**payload, "accepted": True}))
    with pytest.raises(ValueError):
        verify_block_bytes(structured, content.canonical_dag_json_bytes(payload) + b"\n")


@pytest.mark.parametrize("invalid", [1.0, b"bytes", (1,), {1}, {1: "key"}])
def test_invalid_structured_types_never_reach_warmed_encoding_cache(invalid):
    content.cid_for_structured({"valid": True})
    before = content._encode_cid_digest.cache_info()
    with pytest.raises(content.StructuredIdentityError):
        content.cid_for_structured(invalid)
    assert content._encode_cid_digest.cache_info() == before


def test_exact_raw_type_and_codec_allowlist_remain_outside_cache():
    class BytesSubclass(bytes):
        pass

    content.cid_for_bytes(b"value")
    before = content._encode_cid_digest.cache_info()
    for raw in (bytearray(b"value"), memoryview(b"value"), BytesSubclass(b"value")):
        with pytest.raises(TypeError):
            content.cid_for_bytes(raw)
    with pytest.raises(content.ContentIdentityError, match="outside"):
        content._cid_from_digest_bytes(b"value", codec="dag-pb")
    assert content._encode_cid_digest.cache_info() == before


def test_base_version_and_whole_multihash_participate_in_key(monkeypatch):
    raw = b"profile-key"
    standard = content.cid_for_bytes(raw)
    monkeypatch.setattr(content, "CID_BASE", "base58btc")
    encoded = content.cid_for_bytes(raw)
    assert encoded == native_cid(raw, codec="raw") != standard
    monkeypatch.setattr(content, "CID_BASE", "base32")
    monkeypatch.setattr(content, "MULTIHASH_TYPE", "sha2-512")
    hashed = content.cid_for_bytes(raw)
    assert hashed == native_cid(raw, codec="raw") != standard
    monkeypatch.setattr(content, "MULTIHASH_TYPE", "sha2-256")
    monkeypatch.setattr(content, "CID_VERSION", 0)
    with pytest.raises(ValueError):
        content.cid_for_bytes(raw)


def test_subclass_key_bypasses_cache_and_keeps_native_result_or_failure(monkeypatch):
    class StringSubclass(str):
        pass

    raw = b"key-subclass"
    content.cid_for_bytes(raw)
    before = content._encode_cid_digest.cache_info()
    monkeypatch.setattr(content, "CID_BASE", StringSubclass("base32"))
    assert content.cid_for_bytes(raw) == native_cid(raw, codec="raw")
    assert content._encode_cid_digest.cache_info() == before
    monkeypatch.setattr(content, "CID_BASE", "base32")
    monkeypatch.setattr(content, "CID_VERSION", True)
    try:
        expected = native_cid(raw, codec="raw")
    except Exception as exc:
        with pytest.raises(type(exc)):
            content.cid_for_bytes(raw)
    else:
        assert content.cid_for_bytes(raw) == expected
    assert content._encode_cid_digest.cache_info() == before


def test_concurrent_reads_return_only_native_canonical_strings():
    inputs = [f"concurrent-{i % 5}".encode() for i in range(40)]
    expected = [native_cid(raw, codec="raw") for raw in inputs]
    with ThreadPoolExecutor(max_workers=4) as executor:
        actual = list(executor.map(content.cid_for_bytes, inputs))
    assert actual == expected
    assert all(type(value) is str for value in actual)
    assert content._encode_cid_digest.cache_info().currsize == 5
