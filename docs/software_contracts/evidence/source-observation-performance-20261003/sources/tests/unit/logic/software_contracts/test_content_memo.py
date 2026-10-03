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
    content._native_registry_layout.cache_clear()
    content._memo_encode_digest.cache_clear()
    content._memo_validate_cid.cache_clear()
    yield
    content._memo_encode_digest.cache_clear()
    content._memo_validate_cid.cache_clear()
    content._native_registry_layout.cache_clear()


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
    vectors = content.load_cid_vectors(fixture)["vectors"]
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


def test_profile_version_changes_do_not_hit_prior_validation(monkeypatch):
    cid = content.cid_for_bytes(b"profile-change")
    content.validate_cid(cid)
    monkeypatch.setattr(content, "CID_VERSION", 0)
    assert outcome(lambda: content.validate_cid(cid)) == outcome(lambda: reference_validate(cid))
    assert outcome(lambda: content.cid_for_bytes(b"profile-change")) == outcome(
        lambda: reference_encode(b"profile-change", "raw"))


def test_both_memos_have_real_bounded_eviction_and_recompute():
    first = content.cid_for_bytes(b"evict-0")
    content.validate_cid(first)
    for index in range(1, content._CID_MEMO_MAXSIZE + 1):
        cid = content.cid_for_bytes(f"evict-{index}".encode())
        content.validate_cid(cid)
    for memo in (content._memo_encode_digest, content._memo_validate_cid):
        assert memo.cache_info().currsize == content._CID_MEMO_MAXSIZE
    encode_misses = content._memo_encode_digest.cache_info().misses
    validate_misses = content._memo_validate_cid.cache_info().misses
    assert content.cid_for_bytes(b"evict-0") == reference_encode(b"evict-0", "raw") == first
    assert content.validate_cid(first) == first
    assert content._memo_encode_digest.cache_info().misses == encode_misses + 1
    assert content._memo_validate_cid.cache_info().misses == validate_misses + 1


def test_repeated_graph_working_set_above_4096_retains_pure_cid_results():
    # A repeated full graph traversal must not turn every lookup into a miss
    # merely because a modest graph has more edges than the old 4096 capacity.
    size = 5000
    values = [{"schema": "memo-edge-control@1", "source": i, "target": i + 1}
              for i in range(size)]
    first = [content.cid_for_structured(value) for value in values]
    assert len(set(first)) == size
    for cid in first:
        content.validate_cid(cid)
    before_encode = content._memo_encode_digest.cache_info()
    before_validate = content._memo_validate_cid.cache_info()
    assert [content.cid_for_structured(value) for value in values] == first
    assert [content.validate_cid(cid) for cid in first] == first
    after_encode = content._memo_encode_digest.cache_info()
    after_validate = content._memo_validate_cid.cache_info()
    assert after_encode.misses == before_encode.misses
    assert after_validate.misses == before_validate.misses
    assert after_encode.hits - before_encode.hits == size
    assert after_validate.hits - before_validate.hits == size
    assert after_encode.currsize == after_validate.currsize == size
    # Caller body mutation still hashes fresh bytes, even on a warm graph.
    values[0]["target"] = -1
    assert content.cid_for_structured(values[0]) != first[0]


def test_parallel_threads_preserve_exact_outputs():
    payloads = [f"parallel-{index % 8}".encode() for index in range(64)]
    expected = [reference_encode(payload, "raw") for payload in payloads]
    def work(payload):
        cid = content.cid_for_bytes(payload)
        return content.decode_and_recompute_source(cid, payload)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(work, payloads)) == expected


@pytest.mark.parametrize("operation", ["encode", "validate"])
def test_registration_drift_during_miss_cannot_poison_prior_key(monkeypatch, operation):
    payload = b"miss-drift"
    expected = reference_encode(payload, "raw")
    saved = multicodec.get("raw")
    changed = multicodec.Multicodec("raw", "ipld", 0x55, "draft", "changed registration")
    drifted = False
    def drift_once():
        nonlocal drifted
        if not drifted:
            drifted = True
            multicodec.unregister("raw")
            multicodec.register(changed)
    if operation == "encode":
        original = CID.__new__
        def construct(cls, *args, **kwargs):
            drift_once()
            return original(cls, *args, **kwargs)
        monkeypatch.setattr(CID, "__new__", staticmethod(construct))
        call = lambda: content.cid_for_bytes(payload)
        memo = content._memo_encode_digest
    else:
        original = content._validate_cid_uncached
        def validate(value, allowed):
            result = original(value, allowed)
            drift_once()
            return result
        monkeypatch.setattr(content, "_validate_cid_uncached", validate)
        call = lambda: content.validate_cid(expected)
        memo = content._memo_validate_cid
    try:
        assert call() == expected
        assert drifted
        assert memo.cache_info().currsize == 0
    finally:
        multicodec.unregister("raw")
        multicodec.register(saved)
    assert call() == expected
    assert memo.cache_info().currsize == 1


@pytest.mark.parametrize("operation", ["encode", "validate"])
def test_registration_drift_after_warm_lookup_is_not_hidden(monkeypatch, operation):
    payload = b"hit-drift"
    cid = content.cid_for_bytes(payload)
    content.validate_cid(cid)
    name = "_memo_encode_digest" if operation == "encode" else "_memo_validate_cid"
    original = getattr(content, name)
    saved = multicodec.get("raw")
    def lookup_then_remove(*args):
        result = original(*args)
        multicodec.unregister("raw")
        return result
    with monkeypatch.context() as patch:
        patch.setattr(content, name, lookup_then_remove)
        try:
            if operation == "encode":
                assert outcome(lambda: content.cid_for_bytes(payload)) == outcome(
                    lambda: reference_encode(payload, "raw"))
            else:
                assert outcome(lambda: content.validate_cid(cid)) == outcome(
                    lambda: reference_validate(cid))
        finally:
            multicodec.register(saved)


def test_native_table_key_matches_public_key_and_avoids_getter_validation(monkeypatch):
    content.cid_for_bytes(b"initialize native raw entries")
    assert content._native_registry_layout() is not None
    expected = content._memo_registration_key_slow()
    def slow_tripwire():
        raise AssertionError("native standard registry unexpectedly used slow key")
    monkeypatch.setattr(content, "_memo_registration_key_slow", slow_tripwire)
    for _ in range(4):
        assert content._memo_registration_key() == expected


def test_live_replaced_native_tables_are_read_without_retaining_old_dict(monkeypatch):
    content.cid_for_bytes(b"table replacement")
    original = dict(multicodec._name_table)
    replacement = dict(original)
    monkeypatch.setattr(multicodec, "_name_table", replacement)
    assert content._memo_registration_key() == content._memo_registration_key_slow()
    replacement.pop("raw")
    assert content._memo_registration_key() is None
    replacement["raw"] = original["raw"]
    assert content._memo_registration_key() == content._memo_registration_key_slow()


def test_non_native_mapping_uses_public_lookup(monkeypatch):
    content.cid_for_bytes(b"custom registry mapping")
    accesses = []
    class ObservedMap(dict):
        def __getitem__(self, key):
            accesses.append(key)
            return super().__getitem__(key)
    monkeypatch.setattr(multicodec, "_name_table", ObservedMap(multicodec._name_table))
    assert content._memo_registration_key() == content._memo_registration_key_slow()
    assert "raw" in accesses and "sha2-256" in accesses


@pytest.mark.parametrize("initialize_native", [True, False])
def test_replaced_public_getter_falls_back_even_on_first_use(monkeypatch, initialize_native):
    if initialize_native:
        content.cid_for_bytes(b"warm getter bindings")
        assert content._native_registry_layout() is not None
    original = multicodec.get
    calls = []
    def get(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(multicodec, "get", get)
    key = content._memo_registration_key()
    assert key is not None and calls
    if not initialize_native:
        assert content._native_registry_layout() is None


def test_replaced_hash_property_uses_public_behavior(monkeypatch):
    cid = content.cid_for_bytes(b"property binding")
    content.validate_cid(cid)
    monkeypatch.setattr(multihash.Multihash, "max_digest_size", property(lambda self: 16))
    assert content._memo_registration_key() is None
    assert outcome(lambda: content.validate_cid(cid)) == outcome(lambda: reference_validate(cid))


def test_missing_lazy_raw_registration_uses_public_jit(monkeypatch):
    cid = content.cid_for_bytes(b"lazy raw binding")
    original = multibase.raw._raw_encodings
    replacement = dict(original)
    replacement.pop("base32")
    monkeypatch.setattr(multibase.raw, "_raw_encodings", replacement)
    assert content._memo_registration_key() == content._memo_registration_key_slow()
    assert "base32" in replacement
    assert content.validate_cid(cid) == cid


def test_unsupported_native_version_keeps_public_path(monkeypatch):
    import multiformats
    monkeypatch.setattr(multiformats, "__version__", "future-unsupported")
    assert content._native_registry_layout() is None
    assert content._memo_registration_key() == content._memo_registration_key_slow()


def test_live_encoding_class_replacement_uses_public_path(monkeypatch):
    from bases.encoding import fixchar
    content.cid_for_bytes(b"encoding class binding")
    assert content._native_registry_layout() is not None
    monkeypatch.setattr(fixchar, "FixcharBaseEncoding", type("Replacement", (), {}))
    assert content._memo_registration_key() is None
    assert content._memo_registration_key_slow() is None


def test_live_version_change_uses_public_path(monkeypatch):
    import multiformats
    content.cid_for_bytes(b"live version binding")
    assert content._native_registry_layout() is not None
    monkeypatch.setattr(multiformats, "__version__", "future-unsupported")
    calls = []
    original = content._memo_registration_key_slow
    def slow():
        calls.append(True)
        return original()
    monkeypatch.setattr(content, "_memo_registration_key_slow", slow)
    assert content._memo_registration_key() == original()
    assert calls
