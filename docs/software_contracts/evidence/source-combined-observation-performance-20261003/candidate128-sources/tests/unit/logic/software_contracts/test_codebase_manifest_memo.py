"""Pure reconstruction reuse never replaces fresh source/CAS/head authority."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json

import pytest
from multiformats import multihash

from ipfs_datasets_py.logic.software_contracts import codebase_ir as owner
from ipfs_datasets_py.logic.software_contracts import content
from ipfs_datasets_py.logic.software_contracts.cache import ImmutableCAS, CacheIntegrityError
from ipfs_datasets_py.logic.software_contracts.semantic_index import identity, models
from ipfs_datasets_py.logic.software_contracts.semantic_index.scanner import RepositoryScanner
from ipfs_datasets_py.logic.software_contracts.semantic_index.snapshot import snapshot_repository


@pytest.fixture(autouse=True)
def empty_cache():
    with owner._MANIFEST_MEMO_LOCK:
        owner._MANIFEST_MEMO.clear(); owner._MANIFEST_MEMO_SIZE = 0
        owner._MANIFEST_MEMO_STATS.update(hits=0, misses=0, evictions=0, bypasses=0)
    yield
    with owner._MANIFEST_MEMO_LOCK:
        owner._MANIFEST_MEMO.clear(); owner._MANIFEST_MEMO_SIZE = 0


@pytest.fixture
def specimen(tmp_path):
    path = tmp_path / "source"; path.mkdir()
    (path / "unit.py").write_text("def increment(n: int) -> int:\n    return n + 1\n")
    def make(repository_id="memo-fixture"):
        snapshot = snapshot_repository(path, repository_id=repository_id)
        state = RepositoryScanner(repository_id=repository_id).scan_snapshot(snapshot,
            {entry.source_key: entry.captured_bytes for entry in snapshot.entries})
        units = tuple(owner.CodebaseUnit(entry.source_key, entry.entry_cid, None, "unindexed")
                      for entry in snapshot.entries)
        manifest = owner.CodebaseIRManifest(snapshot, state,
            f"rev:{repository_id}:snapshot:{snapshot.snapshot_cid}", units)
        return manifest.to_dict(), manifest.cid
    return make


def test_private_graph_input_output_and_forced_record_mutations_are_detached(specimen):
    value, cid = specimen(); original = json.loads(json.dumps(value))
    first = owner._reconstruct_manifest(value, cid)
    value["coverage"]["inventory_entries"] = 900
    detached = first.to_dict()
    detached["semantic_state"]["symbols"][0]["metadata"]["injected"] = True
    with pytest.raises((TypeError, FrozenInstanceError)):
        first.semantic_state.symbols[0].metadata["injected"] = True
    object.__setattr__(first.semantic_state.symbols[0], "qualified_name", "poisoned")
    object.__setattr__(first.snapshot.entries[0], "path", "poisoned.py")
    second = owner._reconstruct_manifest(original, cid)
    assert second.to_dict() == original
    assert second is not first
    assert owner._MANIFEST_MEMO_STATS["hits"] == 1


def test_every_warm_index_load_still_reads_and_hashes_current_cas(specimen, tmp_path):
    value, cid = specimen(); cas = ImmutableCAS(tmp_path / "cas")
    assert cas.put(value) == cid
    index = owner.RepositoryCodebaseIndex(artifacts=cas)
    assert index.load(cid).cid == cid
    assert index.load(cid).cid == cid
    path = cas.path_for(cid); original = path.read_bytes()
    path.write_bytes(original.replace(b"memo-fixture", b"evil-fixture", 1))
    with pytest.raises(CacheIntegrityError):
        index.load(cid)
    path.write_bytes(original)
    assert index.load(cid).cid == cid
    path.unlink()
    with pytest.raises(FileNotFoundError):
        index.load(cid)


@pytest.mark.parametrize("replacement", ["constructor", "property", "identity", "default", "schema"])
@pytest.mark.parametrize("warm", [False, True])
def test_changed_producer_cannot_hit_prior_result(specimen, monkeypatch, replacement, warm):
    value, cid = specimen()
    if warm:owner._reconstruct_manifest(value, cid)
    if replacement == "constructor":
        original = owner.CodebaseIRManifest.from_dict
        monkeypatch.setattr(owner.CodebaseIRManifest, "from_dict", classmethod(lambda cls, v: original(v)))
    elif replacement == "property":
        original = owner.CodebaseIRManifest.cid.fget
        monkeypatch.setattr(owner.CodebaseIRManifest, "cid", property(lambda self: original(self)))
    elif replacement == "identity":
        original = identity.normalize_ast
        monkeypatch.setattr(identity, "normalize_ast", lambda value: original(value))
    elif replacement == "default":
        monkeypatch.setattr(identity.symbol_version_cid, "__kwdefaults__",
                            {**identity.symbol_version_cid.__kwdefaults__, "property_role": "changed-default"})
    else:
        monkeypatch.setattr(models, "SEMANTIC_INDEX_SCHEMA", "unrecognized-schema")
    assert owner._manifest_producer_key() is None
    if replacement == "schema":
        with pytest.raises(ValueError):owner._reconstruct_manifest(value, cid)
    else:
        assert owner._reconstruct_manifest(value, cid).cid == cid
    assert owner._MANIFEST_MEMO_STATS["hits"] == 0
    assert owner._MANIFEST_MEMO_STATS["bypasses"] == 1


def test_wrong_identity_and_invalid_coverage_do_not_reuse_valid_graph(specimen):
    value, cid = specimen(); owner._reconstruct_manifest(value, cid)
    with pytest.raises(owner.CodebaseIRError, match="identity"):
        owner._reconstruct_manifest(value, content.cid_for_structured({"wrong": True}))
    value["coverage"]["checked_properties"] = 1
    with pytest.raises(owner.CodebaseIRError, match="coverage"):
        owner._reconstruct_manifest(value, content.cid_for_structured(value))


def test_live_hash_registration_drift_cannot_hit_prior_graph(specimen):
    value, cid = specimen(); owner._reconstruct_manifest(value, cid)
    implementation, size = multihash.raw.get("sha2-256")
    class UnhashableHash:
        __hash__ = None
        def __call__(self, data, size=None):return implementation(data, size)
    multihash.raw.register("sha2-256", UnhashableHash(), size, overwrite=True)
    try:
        assert owner._reconstruct_manifest(value, cid).cid == cid
        assert owner._MANIFEST_MEMO_STATS["hits"] == 0
        assert owner._MANIFEST_MEMO_STATS["bypasses"] == 1
    finally:
        multihash.raw.register("sha2-256", implementation, size, overwrite=True)
    assert owner._reconstruct_manifest(value, cid).cid == cid
    assert owner._MANIFEST_MEMO_STATS["hits"] == 1


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("drift", ["producer", "registry"])
def test_drift_during_miss_or_hit_refuses_before_return(specimen, monkeypatch, warm, drift):
    value, cid = specimen()
    if warm:owner._reconstruct_manifest(value, cid)
    original = owner._manifest_clone
    implementation, size = multihash.raw.get("sha2-256")
    changed = [False]
    def clone(value):
        result = original(value)
        if not changed[0]:
            changed[0] = True
            if drift == "producer":monkeypatch.setattr(models, "SEMANTIC_INDEX_SCHEMA", "changed")
            else:multihash.raw.register("sha2-256", implementation, 16, overwrite=True)
        return result
    monkeypatch.setattr(owner, "_manifest_clone", clone)
    try:
        with pytest.raises(owner.CodebaseIRError, match="producer or registry changed"):
            owner._reconstruct_manifest(value, cid)
        assert owner._MANIFEST_MEMO_STATS["hits"] == 0
        if not warm:assert not owner._MANIFEST_MEMO
    finally:
        multihash.raw.register("sha2-256", implementation, size, overwrite=True)


def test_entry_and_byte_eviction_and_oversized_uncached_parity(specimen, monkeypatch):
    samples = [specimen(f"repository-{i}") for i in range(owner._MANIFEST_MEMO_ENTRIES + 1)]
    for value, cid in samples:assert owner._reconstruct_manifest(value, cid).cid == cid
    assert len(owner._MANIFEST_MEMO) == owner._MANIFEST_MEMO_ENTRIES
    assert owner._MANIFEST_MEMO_STATS["evictions"] == 1
    assert owner._MANIFEST_MEMO_SIZE <= owner._MANIFEST_MEMO_BYTES
    owner._reconstruct_manifest(*samples[0])
    assert owner._MANIFEST_MEMO_STATS["misses"] == len(samples) + 1
    with owner._MANIFEST_MEMO_LOCK:
        owner._MANIFEST_MEMO.clear(); owner._MANIFEST_MEMO_SIZE = 0
    monkeypatch.setattr(owner, "_MANIFEST_MEMO_BYTES", 1)
    for _ in range(2):
        result = owner._reconstruct_manifest(*samples[0])
        assert result.to_dict() == samples[0][0]
    assert not owner._MANIFEST_MEMO and owner._MANIFEST_MEMO_SIZE == 0


def test_byte_budget_evicts_before_entry_limit(specimen, monkeypatch):
    first = specimen("one"); second = specimen("two")
    owner._reconstruct_manifest(*first)
    single_size = owner._MANIFEST_MEMO_SIZE
    monkeypatch.setattr(owner, "_MANIFEST_MEMO_BYTES", single_size + 1024)
    owner._reconstruct_manifest(*second)
    assert len(owner._MANIFEST_MEMO) == 1
    assert owner._MANIFEST_MEMO_STATS["evictions"] == 1
    assert owner._MANIFEST_MEMO_SIZE <= owner._MANIFEST_MEMO_BYTES


def test_threaded_exact_replay_returns_independent_records(specimen):
    value, cid = specimen(); owner._reconstruct_manifest(value, cid)
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda _: owner._reconstruct_manifest(value, cid), range(9)))
    assert all(row.to_dict() == value for row in rows)
    assert len({id(row) for row in rows}) == len(rows)
    assert len({id(row.semantic_state.symbols[0]) for row in rows}) == len(rows)
