"""CAS size bounds apply while reading, before parsing or CID verification."""
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.software_contracts.cache import CacheIntegrityError, ImmutableCAS
from ipfs_datasets_py.logic.software_contracts.content import (
    canonical_dag_json_bytes, cid_for_bytes, cid_for_structured,
)


def track_reads(monkeypatch, target, maximum):
    """Keep the real file read while refusing any unbounded allocation."""
    original = Path.open
    reads = []

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            assert 0 <= size <= maximum, "CAS attempted an unbounded file read"
            data = self.stream.read(size)
            reads.append((size, len(data)))
            return data

    def tracked(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        return Reader(stream) if path == target and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", tracked)
    return reads


@pytest.mark.parametrize("source", [False, True])
def test_oversized_sparse_object_reads_only_limit_plus_sentinel(tmp_path, monkeypatch, source):
    limit = 64
    cas = ImmutableCAS(tmp_path, max_object_bytes=limit)
    cid = cid_for_bytes(b"source") if source else cid_for_structured({"schema": "test@1"})
    target = cas.path_for(cid, source=source)
    target.parent.mkdir(parents=True, exist_ok=True)
    # A corrupted sparse object is large on the filesystem without consuming
    # corresponding disk blocks. The reader spy prevents a buggy test run from
    # actually allocating its full one-GiB logical size.
    with target.open("wb") as stream:
        stream.write(b"x")
        stream.truncate(1024 ** 3)
    assert target.stat().st_size == 1024 ** 3
    reads = track_reads(monkeypatch, target, limit + 1)

    with pytest.raises(CacheIntegrityError, match="exceeds max_object_bytes"):
        (cas.get_bytes if source else cas.get)(cid)
    assert reads == [(limit + 1, limit + 1)]


@pytest.mark.parametrize("source", [False, True])
def test_exact_limit_object_still_verifies_and_roundtrips(tmp_path, monkeypatch, source):
    value = b"\x00source\xff" if source else {"schema": "test@1", "value": "exact bound"}
    payload = value if source else canonical_dag_json_bytes(value)
    cas = ImmutableCAS(tmp_path, max_object_bytes=len(payload))
    cid = (cas.put_bytes if source else cas.put)(value)
    target = cas.path_for(cid, source=source)
    reads = track_reads(monkeypatch, target, len(payload) + 1)

    assert (cas.get_bytes if source else cas.get)(cid) == value
    assert reads == [(len(payload) + 1, len(payload))]


@pytest.mark.parametrize("source", [False, True])
def test_missing_object_preserves_file_not_found_error(tmp_path, source):
    cas = ImmutableCAS(tmp_path, max_object_bytes=64)
    cid = cid_for_bytes(b"missing") if source else cid_for_structured({"missing": True})
    with pytest.raises(FileNotFoundError):
        (cas.get_bytes if source else cas.get)(cid)


@pytest.mark.parametrize("source", [False, True])
def test_io_error_remains_wrapped_as_integrity_error(tmp_path, source):
    cas = ImmutableCAS(tmp_path, max_object_bytes=64)
    cid = cid_for_bytes(b"directory") if source else cid_for_structured({"directory": True})
    cas.path_for(cid, source=source).mkdir(parents=True)
    with pytest.raises(CacheIntegrityError, match="cannot read") as caught:
        (cas.get_bytes if source else cas.get)(cid)
    assert isinstance(caught.value.__cause__, OSError)


def test_sparse_oversized_index_reads_only_limit_plus_sentinel(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.software_contracts.cache import AnalysisCache, MAX_INDEX_RECORD_BYTES

    cache = AnalysisCache(tmp_path)
    key_cid = cid_for_structured({"key": "bounded-index-test"})
    target = cache._index_path(key_cid)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream:
        stream.write(b"x")
        stream.truncate(1024 ** 3)
    reads = track_reads(monkeypatch, target, MAX_INDEX_RECORD_BYTES + 1)
    with pytest.raises(CacheIntegrityError, match="index record exceeds byte bound"):
        cache._read_index(key_cid)
    assert reads == [(MAX_INDEX_RECORD_BYTES + 1, MAX_INDEX_RECORD_BYTES + 1)]


def test_index_missing_and_io_error_are_distinguished(tmp_path):
    from ipfs_datasets_py.logic.software_contracts.cache import AnalysisCache

    cache = AnalysisCache(tmp_path)
    key_cid = cid_for_structured({"key": "missing"})
    assert cache._read_index(key_cid) is None
    cache._index_path(key_cid).mkdir(parents=True)
    with pytest.raises(CacheIntegrityError, match="cannot read cache index"):
        cache._read_index(key_cid)
