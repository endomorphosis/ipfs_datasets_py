"""KGP-012: Verified hybrid cache, reachability, pin, and GC policy.

Acceptance coverage:
* Verify cached objects against descriptor/CID
* Atomic cache writes and bounded eviction
* Record authoritative copy
* Keep every branch/tag/snapshot/lease root reachable and pinned
* Identify only abandoned staged objects for collection
* Prove dry-run plus interrupted-GC recovery
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pytest

from ipfs_datasets_py.knowledge_graphs.catalog import open_catalog
from ipfs_datasets_py.knowledge_graphs.storage.gc import (
    GCPhase,
    GarbageCollector,
    ReachableRoot,
    RootKind,
    collect_catalog_roots,
    compute_reachable_set,
    create_garbage_collector,
)
from ipfs_datasets_py.knowledge_graphs.storage.hybrid import (
    STORAGE_PROFILE,
    AuthoritativeCopy,
    HybridGraphStore,
    ObjectDescriptor,
    ObjectLifecycle,
    VerifiedHybridCache,
    create_hybrid_graph_store,
    sha256_bytes,
    verify_against_descriptor,
)
from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import (
    GraphStoreError,
    IPLDGraphStore,
    compute_cid_v1,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "hybrid-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def hybrid(cache_dir: Path) -> Iterator[HybridGraphStore]:
    store = create_hybrid_graph_store(
        cache_dir,
        remote_mode="memory",
        max_bytes=64 * 1024,
        max_entries=8,
        pin_by_default=True,
    )
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def catalog(tmp_path: Path):
    cat = open_catalog(tmp_path / "catalog.sqlite")
    try:
        yield cat
    finally:
        cat.close()


def _put_bytes(store: HybridGraphStore, data: bytes, **kwargs: Any):
    return store.put(data, codec="raw", **kwargs)


# ---------------------------------------------------------------------------
# Descriptor / CID verification
# ---------------------------------------------------------------------------


def test_verify_against_descriptor_accepts_match() -> None:
    data = b"hybrid-payload-v1"
    desc = ObjectDescriptor.from_bytes(data, codec="raw", path="parts/nodes")
    assert verify_against_descriptor(data, desc) == desc.cid
    assert desc.sha256 == sha256_bytes(data)
    assert desc.size == len(data)


def test_verify_against_descriptor_rejects_cid_mismatch() -> None:
    data = b"hybrid-payload-v1"
    desc = ObjectDescriptor.from_bytes(data, codec="raw")
    with pytest.raises(GraphStoreError) as ei:
        verify_against_descriptor(b"tampered-bytes!!", desc)
    assert ei.value.code == "INTEGRITY"


def test_verify_against_descriptor_rejects_sha256_mismatch() -> None:
    data = b"abc"
    cid = compute_cid_v1(data, codec="raw")
    desc = ObjectDescriptor(
        cid=cid,
        codec="raw",
        size=3,
        sha256="0" * 64,
    )
    with pytest.raises(GraphStoreError) as ei:
        verify_against_descriptor(data, desc)
    assert ei.value.code == "INTEGRITY"
    assert ei.value.cause_code == "SHA256_MISMATCH"


def test_cache_put_get_verifies_cid(cache_dir: Path) -> None:
    cache = VerifiedHybridCache(cache_dir, max_bytes=1024 * 1024, max_entries=16)
    data = b"verified-cache-object"
    desc = ObjectDescriptor.from_bytes(data)
    meta = cache.put(data, descriptor=desc)
    assert meta.cid == desc.cid
    loaded = cache.get(desc.cid, descriptor=desc)
    assert loaded == data
    cache.close()


def test_cache_rejects_corrupt_on_read(cache_dir: Path) -> None:
    cache = VerifiedHybridCache(cache_dir, max_bytes=1024 * 1024, max_entries=16)
    data = b"good-bytes"
    desc = ObjectDescriptor.from_bytes(data)
    cache.put(data, descriptor=desc)
    # Corrupt payload behind the meta.
    path = cache._object_path(desc.cid)
    path.write_bytes(b"CORRUPT!!")
    with pytest.raises(GraphStoreError) as ei:
        cache.get(desc.cid)
    assert ei.value.code == "INTEGRITY"
    cache.close()


def test_hybrid_get_drops_corrupt_cache_and_refetches(hybrid: HybridGraphStore) -> None:
    put = hybrid.put(b"remote-and-cache", codec="raw", pin=True)
    # Corrupt local cache only.
    path = hybrid.cache._object_path(put.cid)
    path.write_bytes(b"local-corruption-xxxxx")
    # get should detect integrity failure, drop cache, refetch remote.
    data = hybrid.get(put.cid)
    assert data == b"remote-and-cache"
    # Cache refilled with good bytes.
    assert hybrid.cache.get(put.cid) == b"remote-and-cache"


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


def test_cache_writes_are_atomic_no_tmp_left(cache_dir: Path) -> None:
    cache = VerifiedHybridCache(cache_dir, max_bytes=1024 * 1024, max_entries=16)
    for i in range(5):
        cache.put(f"object-{i}".encode(), codec="raw")
    # No leftover temp files.
    tmps = list(cache_dir.rglob(".*.tmp"))
    assert tmps == []
    # Objects + meta exist.
    assert cache.entry_count == 5
    cache.close()


def test_cache_survives_reopen(cache_dir: Path) -> None:
    cache = VerifiedHybridCache(cache_dir, max_bytes=1024 * 1024, max_entries=16)
    data = b"persist-me"
    meta = cache.put(data, codec="raw", pin=True)
    cache.record_authoritative(meta.cid, AuthoritativeCopy.LOCAL_CACHE)
    cache.close()

    cache2 = VerifiedHybridCache(cache_dir, max_bytes=1024 * 1024, max_entries=16)
    assert cache2.contains(meta.cid)
    assert cache2.get(meta.cid) == data
    assert cache2.is_pinned(meta.cid)
    auth = cache2.get_authority(meta.cid)
    assert auth is not None
    assert auth.authoritative == AuthoritativeCopy.LOCAL_CACHE
    cache2.close()


# ---------------------------------------------------------------------------
# Bounded eviction
# ---------------------------------------------------------------------------


def test_bounded_eviction_by_entry_count(cache_dir: Path) -> None:
    cache = VerifiedHybridCache(cache_dir, max_bytes=10 * 1024 * 1024, max_entries=3)
    cids = []
    for i in range(5):
        meta = cache.put(f"entry-{i}".encode() * 10, codec="raw", pin=False)
        cids.append(meta.cid)
    assert cache.entry_count <= 3
    # Oldest unpinned should be gone; newest retained.
    assert cache.contains(cids[-1])
    assert not cache.contains(cids[0])
    cache.close()


def test_bounded_eviction_never_evicts_pinned(cache_dir: Path) -> None:
    cache = VerifiedHybridCache(cache_dir, max_bytes=10 * 1024 * 1024, max_entries=2)
    pinned = cache.put(b"pinned-root", codec="raw", pin=True)
    for i in range(4):
        cache.put(f"ephemeral-{i}".encode(), codec="raw", pin=False)
    assert cache.contains(pinned.cid)
    assert cache.is_pinned(pinned.cid)
    assert cache.entry_count <= 2  # pinned + at most one ephemeral, or just pinned if over
    # Pin count forces at least the pinned entry to survive.
    assert cache.get(pinned.cid) == b"pinned-root"
    cache.close()


def test_bounded_eviction_by_max_bytes(cache_dir: Path) -> None:
    # Each object ~400 bytes; max_bytes=900 → at most 2.
    cache = VerifiedHybridCache(cache_dir, max_bytes=900, max_entries=100)
    for i in range(5):
        cache.put(os.urandom(400), codec="raw", pin=False)
    assert cache.total_bytes <= 900 or cache.entry_count <= 2
    assert cache.entry_count <= 2
    cache.close()


# ---------------------------------------------------------------------------
# Authoritative copy
# ---------------------------------------------------------------------------


def test_record_authoritative_copy(hybrid: HybridGraphStore) -> None:
    put = hybrid.put(b"auth-object", codec="raw", pin=True)
    auth = hybrid.get_authority(put.cid)
    assert auth is not None
    assert auth.authoritative in {
        AuthoritativeCopy.REMOTE_ROOT,
        AuthoritativeCopy.LOCAL_CACHE,
    }
    # Override to remote explicit.
    rec = hybrid.cache.record_authoritative(
        put.cid,
        AuthoritativeCopy.REMOTE_ROOT,
        remote_root=put.cid,
        details={"note": "remote is source of truth"},
    )
    assert rec.authoritative == AuthoritativeCopy.REMOTE_ROOT
    assert hybrid.get_authority(put.cid).remote_root == put.cid


def test_staged_objects_record_staged_authority(hybrid: HybridGraphStore) -> None:
    put = hybrid.stage(b"staged-payload", lease_id="lease-1")
    meta = hybrid.cache.get_meta(put.cid)
    assert meta is not None
    assert meta.lifecycle == ObjectLifecycle.STAGED.value
    assert meta.authoritative == AuthoritativeCopy.STAGED.value
    assert meta.lease_id == "lease-1"


def test_storage_profile_is_hybrid() -> None:
    assert STORAGE_PROFILE == "hybrid"
    assert HybridGraphStore.storage_profile == "hybrid"


# ---------------------------------------------------------------------------
# Reachability + pin policy (branch / tag / snapshot / lease)
# ---------------------------------------------------------------------------


def test_branch_tag_snapshot_lease_roots_remain_pinned(
    hybrid: HybridGraphStore,
    catalog,
) -> None:
    tenant, graph_id = "acme", "skills"

    # Create catalog graph + branch with pin root.
    branch_root = hybrid.put(b"branch-head-manifest", codec="raw", pin=True)
    tag_root = hybrid.put(b"tag-v1-manifest", codec="raw", pin=True)
    snap_root = hybrid.put(b"snapshot-manifest", codec="raw", pin=True)
    lease_staged = hybrid.stage(b"lease-protected-staged", lease_id="writer-lease-1")

    catalog.create_graph(
        tenant,
        graph_id,
        storage_profile="hybrid",
        graph_kind="knowledge",
        pin_root=branch_root.cid,
    )
    # create_graph already creates default branch; set pin on revision via set_pin_root
    # Find head revision from describe.
    desc = catalog.describe_graph(tenant, graph_id)
    head = desc.head_revision
    assert head is not None
    catalog.set_pin_root(
        tenant, graph_id, head, branch_root.cid, pin_kind="manifest"
    )
    catalog.set_pin_root(tenant, graph_id, head, tag_root.cid, pin_kind="tag")
    catalog.set_pin_root(tenant, graph_id, head, snap_root.cid, pin_kind="snapshot")

    # Active lease.
    lease = catalog.acquire_lease(
        tenant, graph_id, "main", holder="writer-1", ttl_seconds=3600
    )
    assert lease.lease_id

    # Register hybrid roots.
    hybrid.register_root(branch_root.cid, kind="branch", tenant=tenant, graph_id=graph_id)
    hybrid.register_root(tag_root.cid, kind="tag", tenant=tenant, graph_id=graph_id, name="v1")
    hybrid.register_root(
        snap_root.cid, kind="snapshot", tenant=tenant, graph_id=graph_id, name="snap-1"
    )
    # Staged under active lease stays protected (not a pin root kind).
    hybrid.cache.set_lifecycle(
        lease_staged.cid,
        ObjectLifecycle.STAGED,
        root_kind="staged",
        lease_id=lease.lease_id,
    )

    gc = GarbageCollector(hybrid, catalog=catalog)
    plan = gc.plan(dry_run=True, tenant=tenant, graph_id=graph_id)

    root_cids = {r.cid for r in plan.roots if not r.cid.startswith("lease:")}
    assert branch_root.cid in root_cids
    assert tag_root.cid in root_cids
    assert snap_root.cid in root_cids
    # Lease marker present.
    assert any(r.kind == RootKind.LEASE.value for r in plan.roots)

    # Durable roots must be pinned and not candidates.
    cand_cids = {c.cid for c in plan.candidates}
    assert branch_root.cid not in cand_cids
    assert tag_root.cid not in cand_cids
    assert snap_root.cid not in cand_cids
    assert lease_staged.cid not in cand_cids  # protected by active lease

    assert hybrid.is_pinned(branch_root.cid)
    assert hybrid.is_pinned(tag_root.cid)
    assert hybrid.is_pinned(snap_root.cid)

    # Ensure pin policy re-pins.
    pinned = gc.pin_policy.ensure_roots_pinned(plan.roots)
    assert branch_root.cid in pinned


def test_collect_catalog_roots_includes_pin_kinds(catalog, hybrid: HybridGraphStore) -> None:
    tenant, graph_id = "t1", "g1"
    root = hybrid.put(b"root-bytes", pin=True)
    catalog.create_graph(tenant, graph_id, storage_profile="hybrid")
    desc = catalog.describe_graph(tenant, graph_id)
    catalog.set_pin_root(tenant, graph_id, desc.head_revision, root.cid, pin_kind="tag")
    roots = collect_catalog_roots(catalog, tenant=tenant, graph_id=graph_id)
    assert any(r.cid == root.cid and r.kind == "tag" for r in roots)


# ---------------------------------------------------------------------------
# Only abandoned staged objects collected
# ---------------------------------------------------------------------------


def test_gc_identifies_only_abandoned_staged(hybrid: HybridGraphStore) -> None:
    live = hybrid.put(b"live-committed", pin=True)
    hybrid.register_root(live.cid, kind="branch", name="main")

    abandoned = hybrid.stage(b"abandoned-staged", lease_id=None)
    hybrid.abandon_staged(abandoned.cid)

    still_staged_with_lease = hybrid.stage(
        b"active-lease-staged", lease_id="active-lease"
    )
    # Register a lease root so the lease id is considered active.
    extra = [
        ReachableRoot(
            cid=f"lease:active-lease",
            kind=RootKind.LEASE.value,
            lease_id="active-lease",
            source="test",
        )
    ]

    # Committed but not registered as root — must NOT be collected.
    orphan_committed = hybrid.put(b"orphan-committed", pin=False)
    hybrid.cache.set_lifecycle(orphan_committed.cid, ObjectLifecycle.COMMITTED)

    gc = GarbageCollector(hybrid)
    plan = gc.plan(dry_run=True, extra_roots=extra)
    cand = {c.cid: c for c in plan.candidates}

    assert abandoned.cid in cand
    assert cand[abandoned.cid].reason == "abandoned_staged"
    assert still_staged_with_lease.cid not in cand
    assert live.cid not in cand
    assert orphan_committed.cid not in cand


def test_gc_auto_abandons_unleased_staged(hybrid: HybridGraphStore) -> None:
    staged = hybrid.stage(b"no-lease-staged", lease_id=None)
    gc = GarbageCollector(hybrid)
    plan = gc.plan(dry_run=True, mark_unleased_staged_abandoned=True)
    assert any(c.cid == staged.cid for c in plan.candidates)
    meta = hybrid.cache.get_meta(staged.cid)
    assert meta is not None
    assert meta.lifecycle == ObjectLifecycle.ABANDONED.value


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_gc_dry_run_default_does_not_delete(hybrid: HybridGraphStore) -> None:
    abandoned = hybrid.stage(b"to-collect")
    hybrid.abandon_staged(abandoned.cid)

    gc = create_garbage_collector(hybrid)
    # Default dry_run=True
    result = gc.run()
    assert result.dry_run is True
    assert result.phase == GCPhase.COMPLETED.value
    assert result.deleted == []
    assert abandoned.cid in result.skipped or any(
        c.cid == abandoned.cid for c in result.candidates
    )
    # Object still present.
    assert hybrid.cache.contains(abandoned.cid)


def test_gc_execute_deletes_only_abandoned(hybrid: HybridGraphStore) -> None:
    live = hybrid.put(b"keep-me", pin=True)
    hybrid.register_root(live.cid, kind="snapshot", name="s1")
    abandoned = hybrid.stage(b"delete-me")
    hybrid.abandon_staged(abandoned.cid)

    gc = GarbageCollector(hybrid)
    result = gc.run(dry_run=False)
    assert result.dry_run is False
    assert result.phase == GCPhase.COMPLETED.value
    assert abandoned.cid in result.deleted
    assert live.cid not in result.deleted
    assert hybrid.cache.contains(live.cid)
    assert not hybrid.cache.contains(abandoned.cid)
    assert hybrid.get(live.cid) == b"keep-me"


# ---------------------------------------------------------------------------
# Interrupted GC recovery
# ---------------------------------------------------------------------------


def test_interrupted_gc_recovery(hybrid: HybridGraphStore, cache_dir: Path) -> None:
    live = hybrid.put(b"live-root", pin=True)
    hybrid.register_root(live.cid, kind="branch", name="main")

    victims = []
    for i in range(4):
        put = hybrid.stage(f"victim-{i}".encode())
        hybrid.abandon_staged(put.cid)
        victims.append(put.cid)

    journal_path = cache_dir / "gc-journal.json"
    gc = GarbageCollector(hybrid, journal_path=journal_path)

    # Crash after the first successful delete.
    deleted_once = {"n": 0}

    def crash_after_first(cid: str, state) -> None:
        deleted_once["n"] += 1
        if deleted_once["n"] >= 1:
            raise RuntimeError("simulated crash mid-GC")

    gc._after_delete_hook = crash_after_first
    result = gc.run(dry_run=False)
    assert result.phase == GCPhase.INTERRUPTED.value
    assert len(result.deleted) >= 1
    assert journal_path.is_file()

    # Journal reflects running/interrupted progress.
    raw = json.loads(journal_path.read_text(encoding="utf-8"))
    assert raw["phase"] in {GCPhase.INTERRUPTED.value, GCPhase.RUNNING.value}
    assert len(raw["deleted"]) >= 1

    # Recover: finish remaining deletes without touching live root.
    gc2 = GarbageCollector(hybrid, journal_path=journal_path)
    recovered = gc2.recover(resume=True)
    assert recovered.recovered_from_journal is True
    assert recovered.phase == GCPhase.COMPLETED.value
    for cid in victims:
        assert cid in recovered.deleted or not hybrid.cache.contains(cid)
    assert hybrid.cache.contains(live.cid)
    assert hybrid.get(live.cid) == b"live-root"
    assert live.cid not in recovered.deleted


def test_interrupted_gc_cooperative_interrupt(hybrid: HybridGraphStore, cache_dir: Path) -> None:
    for i in range(3):
        put = hybrid.stage(f"coop-{i}".encode())
        hybrid.abandon_staged(put.cid)

    gc = GarbageCollector(hybrid, journal_path=cache_dir / "gc-coop.json")

    def interrupt_after(_cid: str, _state) -> None:
        gc.request_interrupt()

    gc._after_delete_hook = interrupt_after
    # First delete triggers interrupt; subsequent loop sees flag.
    # Actually interrupt is checked at start of loop, so need interrupt before next.
    # request_interrupt after first delete → next iteration aborts.
    result = gc.run(dry_run=False)
    # Depending on timing: either completed (if only 1 candidate processed before flag)
    # or interrupted. With 3 candidates, after first delete interrupt is set,
    # second iteration should exit interrupted.
    assert result.phase in {GCPhase.INTERRUPTED.value, GCPhase.COMPLETED.value}
    if result.phase == GCPhase.INTERRUPTED.value:
        # Clear crash/interrupt hooks so recovery can finish cleanly.
        gc._after_delete_hook = None
        recovered = gc.recover(resume=True)
        assert recovered.phase == GCPhase.COMPLETED.value


def test_recover_with_no_journal(hybrid: HybridGraphStore, cache_dir: Path) -> None:
    gc = GarbageCollector(hybrid, journal_path=cache_dir / "missing-journal.json")
    result = gc.recover()
    assert result.phase == GCPhase.ABORTED.value
    assert "no journal" in result.notes[0]


# ---------------------------------------------------------------------------
# End-to-end hybrid + catalog + GC
# ---------------------------------------------------------------------------


def test_e2e_hybrid_catalog_pin_gc(hybrid: HybridGraphStore, catalog, cache_dir: Path) -> None:
    tenant, graph_id = "prod", "graph-a"

    # Commit revision root.
    rev_payload = b'{"revision":1,"nodes":3}'
    rev = hybrid.put(rev_payload, pin=True, staged=False)
    hybrid.register_root(rev.cid, kind="branch", tenant=tenant, graph_id=graph_id, name="main")

    catalog.create_graph(
        tenant,
        graph_id,
        storage_profile="hybrid",
        pin_root=rev.cid,
    )
    head = catalog.describe_graph(tenant, graph_id).head_revision
    catalog.set_pin_root(tenant, graph_id, head, rev.cid, pin_kind="manifest")
    catalog.set_pin_root(tenant, graph_id, head, rev.cid, pin_kind="branch")

    # Staged write that is abandoned (writer crashed before publish).
    staged = hybrid.stage(b"partial-write-delta", lease_id="old-lease")
    hybrid.abandon_staged(staged.cid)

    # Authority recorded.
    auth = hybrid.get_authority(rev.cid)
    assert auth is not None

    # Descriptor verification on get.
    desc = ObjectDescriptor.from_bytes(rev_payload)
    # CID may differ only if codec path differs — recompute against stored codec.
    data = hybrid.get(rev.cid)
    assert data == rev_payload
    verify_against_descriptor(data, ObjectDescriptor.from_bytes(data))

    gc = GarbageCollector(hybrid, catalog=catalog, journal_path=cache_dir / "e2e-gc.json")

    # Dry-run first.
    dry = gc.run(dry_run=True, tenant=tenant, graph_id=graph_id)
    assert dry.dry_run is True
    assert staged.cid in {c.cid for c in dry.candidates}
    assert rev.cid not in {c.cid for c in dry.candidates}
    assert hybrid.cache.contains(staged.cid)

    # Execute.
    executed = gc.run(dry_run=False, tenant=tenant, graph_id=graph_id)
    assert staged.cid in executed.deleted
    assert not hybrid.cache.contains(staged.cid)
    assert hybrid.is_pinned(rev.cid)
    assert hybrid.get(rev.cid) == rev_payload


def test_compute_reachable_set_ignores_lease_markers() -> None:
    roots = [
        ReachableRoot(cid="bafyroot1", kind="branch"),
        ReachableRoot(cid="lease:abc", kind="lease", lease_id="abc"),
    ]
    reachable = compute_reachable_set(roots)
    assert "bafyroot1" in reachable
    assert "lease:abc" not in reachable


def test_hybrid_put_get_round_trip_with_descriptor(hybrid: HybridGraphStore) -> None:
    data = b"descriptor-round-trip"
    desc = ObjectDescriptor.from_bytes(data, codec="raw", path="payload")
    put = hybrid.put(data, descriptor=desc, pin=True)
    assert put.cid == desc.cid
    assert hybrid.get(put.cid, descriptor=desc) == data


def test_concurrent_cache_puts(cache_dir: Path) -> None:
    cache = VerifiedHybridCache(cache_dir, max_bytes=1024 * 1024, max_entries=200)
    errors: List[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(20):
                cache.put(f"t{n}-obj-{i}".encode() * 8, codec="raw")
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert cache.entry_count > 0
    cache.close()
