"""Unit tests for bounded raw-payload custody and streaming dataset sinks."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.wallets.errors import (
    InvalidRequestError,
    ResourceLimitError,
)
from ipfs_datasets_py.processors.wallets.models import RawPayloadPolicy
from ipfs_datasets_py.processors.wallets.protocols import (
    OperationContext,
    RequestLimits,
)
from ipfs_datasets_py.processors.wallets.storage import (
    DirectoryRawPayloadStore,
    InMemoryRawPayloadStore,
    RawPayloadCustodyLimits,
    StreamingDatasetSink,
    digest_bytes,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def context() -> OperationContext:
    return OperationContext(
        request_id="storage-test-1",
        limits=RequestLimits(
            max_items=100,
            max_pages=10,
            max_requests=20,
            max_response_bytes=64 * 1024,
        ),
    )


class _XorEncryptor:
    """Deterministic test encryptor (not for production)."""

    def __init__(self, key: int = 0x5A) -> None:
        self._key = key & 0xFF

    def encrypt(self, plaintext: bytes) -> bytes:
        return bytes(b ^ self._key for b in plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        return bytes(b ^ self._key for b in ciphertext)


def test_custody_limits_require_positive_values() -> None:
    with pytest.raises(InvalidRequestError, match="max_object_bytes"):
        RawPayloadCustodyLimits(max_object_bytes=0)
    with pytest.raises(InvalidRequestError, match="max_total_bytes"):
        RawPayloadCustodyLimits(max_total_bytes=-1)
    with pytest.raises(InvalidRequestError, match="max_objects"):
        RawPayloadCustodyLimits(max_objects=0)
    with pytest.raises(InvalidRequestError, match="max_object_bytes must not exceed"):
        RawPayloadCustodyLimits(max_object_bytes=100, max_total_bytes=50)


def test_inmemory_store_rejects_oversized_before_state_change(
    context: OperationContext,
) -> None:
    store = InMemoryRawPayloadStore(
        limits=RawPayloadCustodyLimits(
            max_object_bytes=16,
            max_total_bytes=64,
            max_objects=8,
        )
    )
    body = b"x" * 17
    with pytest.raises(ResourceLimitError, match="max_object_bytes"):
        _run(store.put(body, context=context))
    assert len(store) == 0
    assert store.total_bytes == 0
    assert store.digests() == frozenset()


def test_inmemory_store_rejects_over_count_before_state_change(
    context: OperationContext,
) -> None:
    store = InMemoryRawPayloadStore(
        limits=RawPayloadCustodyLimits(
            max_object_bytes=64,
            max_total_bytes=256,
            max_objects=2,
        )
    )
    _run(store.put(b"one", context=context))
    _run(store.put(b"two", context=context))
    assert len(store) == 2
    digests_before = store.digests()
    total_before = store.total_bytes

    with pytest.raises(ResourceLimitError, match="max_objects"):
        _run(store.put(b"three", context=context))

    assert len(store) == 2
    assert store.digests() == digests_before
    assert store.total_bytes == total_before
    assert "sha256:" + __import__("hashlib").sha256(b"three").hexdigest() not in digests_before


def test_inmemory_store_rejects_over_total_bytes_before_state_change(
    context: OperationContext,
) -> None:
    store = InMemoryRawPayloadStore(
        limits=RawPayloadCustodyLimits(
            max_object_bytes=32,
            max_total_bytes=40,
            max_objects=10,
        )
    )
    _run(store.put(b"a" * 24, context=context))
    assert store.total_bytes == 24
    with pytest.raises(ResourceLimitError, match="max_total_bytes"):
        _run(store.put(b"b" * 24, context=context))
    assert len(store) == 1
    assert store.total_bytes == 24


def test_inmemory_store_idempotent_put_does_not_inflate_counts(
    context: OperationContext,
) -> None:
    store = InMemoryRawPayloadStore(
        limits=RawPayloadCustodyLimits(
            max_object_bytes=64,
            max_total_bytes=128,
            max_objects=1,
        )
    )
    body = b"same-payload"
    first = _run(store.put(body, context=context))
    second = _run(store.put(body, context=context))
    assert first.digest == second.digest
    assert len(store) == 1
    assert store.total_bytes == len(body)


def test_inmemory_store_bounded_explicit_retention_usable(
    context: OperationContext,
) -> None:
    store = InMemoryRawPayloadStore(
        policy=RawPayloadPolicy.REFERENCED,
        limits=RawPayloadCustodyLimits(
            max_object_bytes=1024,
            max_total_bytes=4096,
            max_objects=16,
        ),
    )
    body = b'{"tx":"0xabc","amount":"1"}'
    stored = _run(store.put(body, media_type="application/json", context=context))
    assert stored.digest == digest_bytes(body)
    loaded = _run(store.get(stored.digest, context=context))
    assert loaded is not None
    assert loaded.body == body
    assert loaded.byte_length == len(body)


def test_inmemory_store_omitted_policy_rejects_put(context: OperationContext) -> None:
    store = InMemoryRawPayloadStore(policy=RawPayloadPolicy.OMITTED)
    with pytest.raises(InvalidRequestError, match="omitted"):
        _run(store.put(b"secret", context=context))
    assert len(store) == 0


def test_inmemory_store_encrypted_mode_fails_closed_without_encryptor() -> None:
    with pytest.raises(InvalidRequestError, match="encryptor"):
        InMemoryRawPayloadStore(policy=RawPayloadPolicy.SEPARATELY_ENCRYPTED)


def test_inmemory_store_encrypted_mode_with_encryptor(
    context: OperationContext,
) -> None:
    encryptor = _XorEncryptor()
    store = InMemoryRawPayloadStore(
        policy=RawPayloadPolicy.SEPARATELY_ENCRYPTED,
        encryptor=encryptor,
        limits=RawPayloadCustodyLimits(
            max_object_bytes=256,
            max_total_bytes=1024,
            max_objects=4,
        ),
    )
    body = b"provider-raw-payload"
    stored = _run(store.put(body, context=context))
    # On-disk/in-memory body is ciphertext.
    assert store._entries[stored.digest].body == encryptor.encrypt(body)
    loaded = _run(store.get(stored.digest, context=context))
    assert loaded is not None
    assert loaded.body == body


def test_directory_store_restrictive_permissions(
    context: OperationContext,
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw-custody"
    store = DirectoryRawPayloadStore(
        root,
        limits=RawPayloadCustodyLimits(
            max_object_bytes=256,
            max_total_bytes=1024,
            max_objects=8,
        ),
    )
    assert root.is_dir()
    dir_mode = stat.S_IMODE(root.stat().st_mode)
    assert dir_mode == 0o700

    stored = _run(store.put(b'{"ok":true}', context=context))
    path = store._path_for(stored.digest)
    assert path.is_file()
    file_mode = stat.S_IMODE(path.stat().st_mode)
    assert file_mode == 0o600
    meta_mode = stat.S_IMODE(path.with_suffix(".meta.json").stat().st_mode)
    assert meta_mode == 0o600


def test_directory_store_rejects_oversized_before_state_change(
    context: OperationContext,
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw-oversize"
    store = DirectoryRawPayloadStore(
        root,
        limits=RawPayloadCustodyLimits(
            max_object_bytes=8,
            max_total_bytes=64,
            max_objects=4,
        ),
    )
    with pytest.raises(ResourceLimitError, match="max_object_bytes"):
        _run(store.put(b"0123456789", context=context))
    assert list(root.glob("*.bin")) == []
    assert list(root.glob("*.meta.json")) == []
    assert len(store) == 0
    assert store.total_bytes == 0


def test_directory_store_rejects_over_count_before_state_change(
    context: OperationContext,
    tmp_path: Path,
) -> None:
    root = tmp_path / "raw-overcount"
    store = DirectoryRawPayloadStore(
        root,
        limits=RawPayloadCustodyLimits(
            max_object_bytes=64,
            max_total_bytes=256,
            max_objects=1,
        ),
    )
    _run(store.put(b"first", context=context))
    files_before = sorted(p.name for p in root.iterdir())
    total_before = store.total_bytes

    with pytest.raises(ResourceLimitError, match="max_objects"):
        _run(store.put(b"second", context=context))

    files_after = sorted(p.name for p in root.iterdir())
    assert files_after == files_before
    assert len(store) == 1
    assert store.total_bytes == total_before


def test_directory_store_operation_max_response_bytes_bound(
    tmp_path: Path,
) -> None:
    tight = OperationContext(
        request_id="tight-bytes",
        limits=RequestLimits(
            max_items=10,
            max_pages=5,
            max_requests=5,
            max_response_bytes=4,
        ),
    )
    store = DirectoryRawPayloadStore(
        tmp_path / "raw-op-bound",
        limits=RawPayloadCustodyLimits(
            max_object_bytes=1024,
            max_total_bytes=4096,
            max_objects=10,
        ),
    )
    with pytest.raises(ResourceLimitError, match="max_response_bytes"):
        _run(store.put(b"12345", context=tight))
    assert len(store) == 0


def test_directory_store_encrypted_mode_fails_closed_without_encryptor(
    tmp_path: Path,
) -> None:
    with pytest.raises(InvalidRequestError, match="encryptor"):
        DirectoryRawPayloadStore(
            tmp_path / "enc",
            policy=RawPayloadPolicy.SEPARATELY_ENCRYPTED,
        )


def test_directory_store_encrypted_round_trip(
    context: OperationContext,
    tmp_path: Path,
) -> None:
    encryptor = _XorEncryptor(0x3C)
    store = DirectoryRawPayloadStore(
        tmp_path / "enc-ok",
        policy=RawPayloadPolicy.SEPARATELY_ENCRYPTED,
        encryptor=encryptor,
        limits=RawPayloadCustodyLimits(
            max_object_bytes=128,
            max_total_bytes=512,
            max_objects=4,
        ),
    )
    body = b"directory-encrypted-body"
    stored = _run(store.put(body, context=context))
    on_disk = store._path_for(stored.digest).read_bytes()
    assert on_disk == encryptor.encrypt(body)
    assert on_disk != body
    loaded = _run(store.get(stored.digest, context=context))
    assert loaded is not None
    assert loaded.body == body


def test_streaming_dataset_sink_stages_and_commits(context: OperationContext) -> None:
    from ipfs_datasets_py.processors.wallets.protocols import RecordBatch

    sink = StreamingDatasetSink(scope="wallet:0xabc")
    batch = RecordBatch(
        (
            {"record_id": "r1", "finality": "confirmed", "ledger_position": {"sequence": 1}},
            {"record_id": "r1", "finality": "confirmed", "ledger_position": {"sequence": 1}},
            {"record_id": "r2", "finality": "finalized", "ledger_position": {"sequence": 2}},
        ),
        response_bytes=32,
    )
    receipt = _run(sink.write(batch, context=context))
    assert receipt.accepted_count == 2
    assert receipt.duplicate_count == 1
    assert sink.staged_count == 2
    commit = _run(sink.commit(None, context=context))
    assert commit.record_count == 2
    assert sink.committed_count == 2
    assert sink.staged_count == 0
