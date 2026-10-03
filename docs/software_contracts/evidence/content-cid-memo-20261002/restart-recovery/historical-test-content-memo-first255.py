"""Exact public CID parity and adversarial controls for the bounded pure memo."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import random

import pytest
from multiformats import CID, multibase, multicodec, multihash

from ipfs_datasets_py.logic.software_contracts import content
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS, CacheIntegrityError


@pytest.fixture(autouse=True)
def empty_memos():
    content._memo_encode_digest.cache_clear()
    content._memo_validate_cid.cache_clear()
    yield
    content._memo_encode_digest.cache_clear()
    content._memo_validate_cid.cache_clear()


def reference_encode(payload, codec):
    return str(CID(content.CID_BASE, content.CID_VERSION, codec,
                   multihash.digest(payload, content.MULTIHASH_TYPE)))


def reference_validate(value, *, codecs=None):
    """The previous public validation path, independent of all memo helpers."""
    if not isinstance(value, str) or not value:
        raise content.ContentIdentityError("CID must be a nonempty string")
    if value != value.lower():
        raise content.ContentIdentityError("CID must be lowercase (canonical base32)")
    allowed = frozenset(codecs) if codecs is not None else frozenset({"raw", "dag-json"})
    if not allowed or not allowed.issubset({"raw", "dag-json"}):
        raise content.ContentIdentityError(
            "CID validation codecs must be a non-empty subset of ['dag-json', 'raw']")
    try:
        parsed = CID.decode(value)
    except Exception as exc:
        raise content.ContentIdentityError("CID is not decodable") from exc
    size = multihash.get(content.MULTIHASH_TYPE).max_digest_size
    if (parsed.version != content.CID_VERSION or parsed.codec.name not in allowed
            or parsed.hashfun.name != content.MULTIHASH_TYPE
            or (size is not None and len(parsed.raw_digest) != size)
            or parsed.base.name != content.CID_BASE or str(parsed) != value):
        raise content.ContentIdentityError(
            "CID must use CIDv1 / base32 / sha2-256 and an allowed codec "
            f"from {sorted(allowed)}")
    return value


def outcome(call):
    try:
        return ("ok", call())
    except Exception as exc:
        cause = exc.__cause__
        return (type(exc), str(exc), None if cause is None else (type(cause), str(cause)))


def test_native_golden_vectors_and_generated_differential():
    fixture = Path(__file__).resolve().parents[4] / content.CID_VECTORS_FIXTURE_RELPATH
    vectors = json.loads(fixture.read_bytes())["vectors"]
    for row in vectors:
        payload = bytes.fromhex(row["bytes_hex"]) if row["domain"] == "source" else bytes.fromhex(row["canonical_hex"])
        assert reference_encode(payload, row["codec"]) == row["expected_cid"]
        for _ in range(2):
            actual = content.cid_for_bytes(payload) if row["domain"] == "source" else content.cid_for_structured(row["value"])
            assert actual == row["expected_cid"]
            assert content.validate_cid(actual) == reference_validate(actual)
    rng = random.Random(741)
    for ordinal in range(64):
        payload = rng.randbytes(ordinal * 7)
        source = reference_encode(payload, "raw")
        value = {"unicode": "café/λ", "rows": [ordinal, None, bool(ordinal % 2), {"hex": payload.hex()}]}
        canonical = content.canonical_dag_json_bytes(value)
        structured = reference_encode(canonical, "dag-json")
        for _ in range(2):
            assert content.cid_for_bytes(payload) == source
            assert content.cid_for_structured(value) == structured
            assert content.cid_for_byte_chunks((payload[i:i+13] for i in range(0, len(payload), 13)), max_chunk_bytes=13) == source
            assert content.validate_cid(source, codecs=("raw",)) == source
            assert content.validate_cid(structured, codecs=["dag-json"]) == structured


def test_warm_encoding_still_hashes_every_body_and_stream_frame(monkeypatch):
    original = multihash.digest
    bodies = []
    def digest(data, *args, **kwargs):
        bodies.append(data)
        return original(data, *args, **kwargs)
    monkeypatch.setattr(multihash, "digest", digest)
    cid = content.cid_for_bytes(b"same body")
    for _ in range(4):
        assert content.decode_and_recompute_source(cid, b"same body") == cid
    assert bodies == [b"same body"] * 5
    with pytest.raises(content.ContentIdentityError, match="does not match"):
        content.decode_and_recompute_source(cid, b"changed body")
    assert bodies[-1] == b"changed body"
    consumed = []
    def frames():
        for frame in (b"same", b" ", b"body"):
            consumed.append(frame)
            yield frame
    assert content.cid_for_byte_chunks(frames(), max_chunk_bytes=4) == cid
    assert consumed == [b"same", b" ", b"body"]
    assert content._memo_encode_digest.cache_info().hits >= 5


def test_mutable_structured_values_are_never_cached():
    value = {"rows": [1, 2]}
    cid = content.cid_for_structured(value)
    assert content.verify_structured_read(cid, value) is value
    value["rows"].append(3)
    with pytest.raises(content.ContentIdentityError, match="does not match"):
        content.verify_structured_read(cid, value)
    assert content.cid_for_structured(value) == reference_encode(b'{"rows":[1,2,3]}', "dag-json")
    value["rows"].append(float("nan"))
    with pytest.raises(content.StructuredIdentityError):
        content.cid_for_structured(value)


@pytest.mark.parametrize("source", [True, False])
def test_actual_cas_corruption_and_deletion_refuse_after_warm_hits(tmp_path, source):
    cas = ImmutableCAS(tmp_path)
    cid = cas.put_bytes(b"original") if source else cas.put({"n": 1})
    read = cas.get_bytes if source else cas.get
    assert read(cid) == read(cid)
    path = cas.path_for(cid, source=source)
    path.write_bytes(b"replaced" if source else b'{"n":2}')
    with pytest.raises(CacheIntegrityError):
        read(cid)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        read(cid)


def test_invalid_values_errors_and_allowed_codec_normalization():
    valid = content.cid_for_bytes(b"same")
    content.validate_cid(valid, codecs=("raw", "dag-json"))
    before = content._memo_validate_cid.cache_info()
    assert content.validate_cid(valid, codecs=(v for v in ("dag-json", "raw", "raw"))) == valid
    assert content._memo_validate_cid.cache_info().hits == before.hits + 1
    wrong_version = str(CID("base58btc", 0, "dag-pb", multihash.digest(b"x", "sha2-256")))
    invalids = [None, "", 3, b"x", "garbage", "b" + "a" * 400, valid.upper(), valid[:-1],
                valid[:-1] + "!", wrong_version,
                str(CID("base32", 1, "raw", multihash.digest(b"x", "sha2-256", size=16))),
                str(CID("base32", 1, "raw", multihash.digest(b"x", "sha1"))),
                str(CID("base58btc", 1, "raw", multihash.digest(b"x", "sha2-256")))]
    for value in invalids:
        expected = outcome(lambda: reference_validate(value))
        for _ in range(2):
            assert outcome(lambda: content.validate_cid(value)) == expected
    for codecs in ([], ["not-profile"], ["dag-json"], "raw", [["raw"]], [True]):
        assert outcome(lambda: content.validate_cid(valid, codecs=codecs)) == outcome(lambda: reference_validate(valid, codecs=codecs))
    assert content._memo_validate_cid.cache_info().currsize == 1


def test_str_subclasses_preserve_identity_and_bypass_memo():
    class UnhashableString(str):
        __hash__ = None
    value = UnhashableString(content.cid_for_bytes(b"x"))
    assert content.validate_cid(value) is value
    assert content.validate_cid(value) is reference_validate(value)
    assert content._memo_validate_cid.cache_info().currsize == 0
    class CodecString(str):
        pass
    native = str(value)
    assert content.validate_cid(native, codecs=[CodecString("raw")]) is native
    assert content._memo_validate_cid.cache_info().currsize == 0


@pytest.mark.parametrize("name", ["raw", "dag-json", "sha2-256"])
def test_registered_codec_removal_never_reuses_warm_results(name):
    payload = b"registration-removal"
    cid = content.cid_for_bytes(payload)
    content.validate_cid(cid)
    saved = multicodec.get(name)
    multicodec.unregister(name)
    try:
        assert outcome(lambda: content.cid_for_bytes(payload)) == outcome(lambda: reference_encode(payload, "raw"))
        assert outcome(lambda: content.validate_cid(cid)) == outcome(lambda: reference_validate(cid))
    finally:
        multicodec.register(saved)
    assert content.cid_for_bytes(payload) == cid and content.validate_cid(cid) == cid


def test_registered_nonstandard_numeric_code_preserves_uncached_behavior():
    payload = b"numeric-registration"
    standard = content.cid_for_bytes(payload)
    content.validate_cid(standard)
    saved = multicodec.get("raw")
    other = multicodec.Multicodec("raw", "ipld", 0x300001, "draft", "test-only registration")
    multicodec.unregister("raw")
    multicodec.register(other)
    try:
        actual = content.cid_for_bytes(payload)
        assert actual != standard and actual == reference_encode(payload, "raw")
        assert content.validate_cid(actual) == reference_validate(actual)
        assert outcome(lambda: content.validate_cid(standard)) == outcome(lambda: reference_validate(standard))
    finally:
        multicodec.unregister("raw")
        multicodec.register(saved)
    assert outcome(lambda: content.validate_cid(actual)) == outcome(lambda: reference_validate(actual))
    assert content.validate_cid(standard) == standard


def test_live_raw_base_replacement_and_removal_preserve_errors():
    cid = content.cid_for_bytes(b"base-registration")
    content.validate_cid(cid)
    saved = multibase.raw.get("base32")
    def failed(*args):
        raise RuntimeError("explicit custom encoder refusal")
    replacement = multibase.raw.CustomEncoding(failed, failed)
    multibase.raw.register("base32", replacement, overwrite=True)
    try:
        assert outcome(lambda: content.cid_for_bytes(b"base-registration")) == outcome(lambda: reference_encode(b"base-registration", "raw"))
        assert outcome(lambda: content.validate_cid(cid)) == outcome(lambda: reference_validate(cid))
    finally:
        multibase.raw.register("base32", saved, overwrite=True)
    base = multibase.get("base32")
    multibase.unregister("base32")
    try:
        assert outcome(lambda: content.validate_cid(cid)) == outcome(lambda: reference_validate(cid))
    finally:
        multibase.register(base)
    assert content.validate_cid(cid) == cid


def test_live_hash_digest_size_and_unhashable_implementation_are_not_hidden():
    payload = b"hash-registration"
    cid = content.cid_for_bytes(payload)
    content.validate_cid(cid)
    implementation, size = multihash.raw.get("sha2-256")
    multihash.raw.register("sha2-256", implementation, 16, overwrite=True)
    try:
        assert outcome(lambda: content.validate_cid(cid)) == outcome(lambda: reference_validate(cid))
        assert outcome(lambda: content.cid_for_bytes(payload)) == outcome(lambda: reference_encode(payload, "raw"))
    finally:
        multihash.raw.register("sha2-256", implementation, size, overwrite=True)
    class UnhashableHash:
        __hash__ = None
        def __call__(self, data, size=None):
            return implementation(data, size)
    multihash.raw.register("sha2-256", UnhashableHash(), size, overwrite=True)
    try:
        assert content.cid_for_bytes(payload) == reference_encode(payload, "raw")
        assert content.validate_cid(cid) == reference_validate(cid)
    finally:
        multihash.raw.register("sha2-256", implementation, size, overwrite=True)


