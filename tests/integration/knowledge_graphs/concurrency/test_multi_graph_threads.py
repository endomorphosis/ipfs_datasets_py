"""
Thread-level multi-graph / multi-tenant concurrency (KGP-008).

Exercises ≥16 graph IDs across multiple tenants with concurrent readers and
writers. No timing-only assertions — outcomes are checked via durable heads,
snapshot stability, and typed conflict/fencing results.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from ipfs_datasets_py.knowledge_graphs.transactions import (
    ConflictError,
    InMemoryBranchStore,
    LeaseFencedError,
)

from .helpers import (
    NUM_GRAPHS,
    TENANTS,
    graph_ids,
    make_mvcc,
    tenant_graph_pairs,
)


class TestMultiGraphThreadWriters:
    def test_sixteen_graphs_two_tenants_sequential_seed_then_parallel_writes(self):
        """
        GIVEN: 16 graph IDs across two tenants on a shared branch store
        WHEN: One writer per graph commits a mutation in parallel threads
        THEN: Every graph head advances and tenants remain isolated by key
        """
        pairs = tenant_graph_pairs()
        assert len(pairs) >= NUM_GRAPHS
        assert {t for t, _ in pairs} == set(TENANTS)

        store = InMemoryBranchStore()
        bootstrap = make_mvcc(holder_id="bootstrap", branch_store=store)
        for tenant, gid in pairs:
            bootstrap.open_snapshot(tenant, gid)

        lock = threading.Lock()
        errors: list = []
        results: dict = {}

        def _write(tenant: str, gid: str) -> None:
            try:
                mvcc = make_mvcc(holder_id=f"w-{tenant}-{gid}", branch_store=store)
                txn = mvcc.begin(tenant, gid, acquire_lease=True)
                mvcc.stage_mutations(
                    txn, entities=[{"id": f"e-{tenant}-{gid}", "type": "Node"}]
                )
                result = mvcc.commit(txn)
                with lock:
                    results[(tenant, gid)] = result["revision"]
            except BaseException as exc:  # noqa: BLE001 — collect for assertion
                with lock:
                    errors.append((tenant, gid, type(exc).__name__, str(exc)))

        with ThreadPoolExecutor(max_workers=NUM_GRAPHS) as pool:
            futs = [pool.submit(_write, t, g) for t, g in pairs]
            for f in as_completed(futs):
                f.result()

        assert not errors, f"writer errors: {errors}"
        assert len(results) == len(pairs)

        reader = make_mvcc(holder_id="reader", branch_store=store)
        for tenant, gid in pairs:
            head = store.get_head(tenant, gid, "main")
            assert head == results[(tenant, gid)]
            assert head != "rev-genesis"
            snap = reader.open_snapshot(tenant, gid)
            assert snap.tenant == tenant
            assert snap.graph_id == gid
            assert snap.revision_id == head

    def test_readers_see_stable_snapshots_during_writes(self):
        """
        GIVEN: Readers open snapshots at genesis on 16 graphs
        WHEN: Writers commit new heads concurrently
        THEN: Reader snapshot revision_ids remain the pre-write values
        """
        pairs = tenant_graph_pairs()
        store = InMemoryBranchStore()
        mvcc = make_mvcc(holder_id="coord", branch_store=store)

        reader_revs = {}
        for tenant, gid in pairs:
            snap = mvcc.open_snapshot(tenant, gid)
            reader_revs[(tenant, gid)] = snap.revision_id

        barrier = threading.Barrier(len(pairs) + 1)

        def _writer(tenant: str, gid: str) -> None:
            w = make_mvcc(holder_id=f"w-{gid}", branch_store=store)
            barrier.wait()
            txn = w.begin(tenant, gid, acquire_lease=True)
            w.stage_mutations(txn, entities=[{"id": f"w-{gid}"}])
            w.commit(txn)

        threads = [
            threading.Thread(target=_writer, args=(t, g), daemon=True) for t, g in pairs
        ]
        for t in threads:
            t.start()
        barrier.wait()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive()

        for (tenant, gid), rev in reader_revs.items():
            still = mvcc.open_snapshot(tenant, gid, revision=rev)
            assert still.revision_id == rev
            head = store.get_head(tenant, gid, "main")
            assert head != rev

    def test_same_graph_concurrent_writers_one_wins_cas(self):
        """
        GIVEN: Two writers on the same tenant/graph/base without exclusive lease
               for the second (CAS conflict path)
        WHEN: Both attempt publish from the same base
        THEN: One publish succeeds; the other raises ConflictError
        """
        store = InMemoryBranchStore()
        tenant, gid = "tenant-alpha", "graph-cas"
        mvcc_a = make_mvcc(holder_id="holder-a", branch_store=store)
        t1 = mvcc_a.begin(tenant, gid, acquire_lease=True)
        base = t1.base_revision
        mvcc_a.stage_mutations(t1, entities=[{"id": "a"}])
        mvcc_a.prepare(t1)

        from ipfs_datasets_py.knowledge_graphs.transactions import (
            IsolationLevel,
            StagedDelta,
            Transaction,
            TransactionState,
            WALPhase,
        )

        mvcc_b = make_mvcc(holder_id="holder-b", branch_store=store)
        t2 = Transaction(
            txn_id="txn-loser",
            isolation_level=IsolationLevel.REPEATABLE_READ,
            state=TransactionState.ACTIVE,
            tenant=tenant,
            graph_id=gid,
            branch="main",
            base_revision=base,
            phase=WALPhase.INTENT,
        )
        mvcc_b._active[t2.txn_id] = t2
        mvcc_b._deltas[t2.txn_id] = StagedDelta(
            txn_id=t2.txn_id,
            tenant=tenant,
            graph_id=gid,
            branch="main",
            base_revision=base,
            entities=[{"id": "b"}],
        )
        mvcc_b.prepare(t2)

        cas1 = mvcc_a.publish(t1)
        assert cas1.success
        mvcc_a.complete(t1)

        with pytest.raises(ConflictError) as ei:
            mvcc_b.publish(t2)
        assert ei.value.details.get("conflict") is True
        assert store.get_head(tenant, gid, "main") == t1.staged_revision_id

    def test_cross_tenant_same_graph_id_isolated(self):
        """
        GIVEN: Two tenants using the identical graph_id string
        WHEN: Each commits a different head
        THEN: Heads remain independent (no cross-tenant leakage)
        """
        store = InMemoryBranchStore()
        gid = "shared-name-graph"
        results = {}
        for tenant, entity in (
            ("tenant-alpha", "a"),
            ("tenant-beta", "b"),
        ):
            mvcc = make_mvcc(holder_id=f"h-{tenant}", branch_store=store)
            txn = mvcc.begin(tenant, gid, acquire_lease=True)
            mvcc.stage_mutations(txn, entities=[{"id": entity}])
            result = mvcc.commit(txn)
            results[tenant] = result["revision"]

        head_a = store.get_head("tenant-alpha", gid, "main")
        head_b = store.get_head("tenant-beta", gid, "main")
        assert head_a == results["tenant-alpha"]
        assert head_b == results["tenant-beta"]
        assert head_a != head_b

        snap_a = store.get_revision("tenant-alpha", gid, head_a)
        assert snap_a.tenant == "tenant-alpha"
        with pytest.raises(KeyError):
            store.get_revision("tenant-beta", gid, head_a)

    def test_stale_fencing_epoch_rejected_under_thread_handoff(self):
        """
        GIVEN: Writer A holds a lease; it expires and writer B steals it
        WHEN: Writer A attempts CAS with the stale epoch
        THEN: LeaseFencedError is raised and head is unchanged
        """
        store = InMemoryBranchStore()
        tenant, gid = "tenant-alpha", "graph-fence"
        store.ensure_branch(tenant, gid, "main")
        lease_a = store.acquire_lease(
            tenant, gid, "main", holder="writer-a", ttl_seconds=0.01
        )
        now_after = lease_a.expires_at + 1.0
        lease_b = store.acquire_lease(
            tenant, gid, "main", holder="writer-b", ttl_seconds=60.0, now=now_after
        )
        assert lease_b.epoch == lease_a.epoch + 1

        head = store.get_head(tenant, gid, "main")
        with pytest.raises(LeaseFencedError):
            store.cas_set_head(
                tenant,
                gid,
                "main",
                expected_revision=head,
                new_revision="rev-stale",
                lease_id=lease_a.lease_id,
                lease_epoch=lease_a.epoch,
                now=now_after,
            )
        assert store.get_head(tenant, gid, "main") == head

    def test_duplicate_idempotency_key_wal_phase_is_noop(self):
        """
        GIVEN: A completed commit with an idempotency key
        WHEN: The COMPLETE phase is re-appended with the same key/seq
        THEN: WAL returns the prior CID and entry count does not grow
        """
        from ipfs_datasets_py.knowledge_graphs.transactions import WALPhase

        mvcc = make_mvcc(holder_id="idem-holder")
        txn = mvcc.begin(
            "tenant-alpha",
            "graph-00",
            acquire_lease=True,
            idempotency_key="idem-thread-1",
        )
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        mvcc.commit(txn)

        history = mvcc.wal.get_transaction_history(txn.txn_id)
        complete_entries = [
            e for e in history if e.resolved_phase() == WALPhase.COMPLETE
        ]
        assert len(complete_entries) == 1
        prior = complete_entries[0]
        count_before = mvcc.wal._entry_count

        # Re-append COMPLETE with same idempotency key + record_seq
        cid2 = mvcc.wal.append_phase(
            txn_id=txn.txn_id,
            phase=WALPhase.COMPLETE,
            operations=[],
            tenant=txn.tenant,
            graph_id=txn.graph_id,
            branch=txn.branch,
            base_revision=txn.base_revision,
            new_revision=txn.staged_revision_id,
            staged_root_cid=txn.staged_root_cid,
            lease_id=txn.lease_id,
            lease_epoch=txn.lease_epoch,
            idempotency_key=txn.idempotency_key,
            record_seq=prior.record_seq,
        )
        # Same CID returned (idempotent); entry count unchanged
        exact = f"idem:{txn.idempotency_key}:COMPLETE:{prior.record_seq}"
        assert exact in mvcc.wal._applied_keys or cid2 in mvcc.wal._applied_keys.values()
        assert cid2 is not None
        assert mvcc.wal._entry_count == count_before
        assert mvcc.store.get_head("tenant-alpha", "graph-00", "main") == txn.staged_revision_id


class TestMixedReadersWriters:
    def test_mixed_reader_writer_threads_across_graphs(self):
        """
        GIVEN: 16 graphs, half written and half only read concurrently
        WHEN: Threads interleave open_snapshot and commit
        THEN: All written graphs have advanced heads; read-only stay genesis
        """
        pairs = tenant_graph_pairs()
        store = InMemoryBranchStore()
        bootstrap = make_mvcc(holder_id="boot", branch_store=store)
        for tenant, gid in pairs:
            bootstrap.open_snapshot(tenant, gid)

        write_pairs = pairs[: len(pairs) // 2]
        read_pairs = pairs[len(pairs) // 2 :]
        lock = threading.Lock()
        errors: list = []
        writes: dict = {}
        reads: list = []

        def _writer(tenant: str, gid: str) -> None:
            try:
                mvcc = make_mvcc(holder_id=f"w-{gid}", branch_store=store)
                txn = mvcc.begin(tenant, gid, acquire_lease=True)
                mvcc.stage_mutations(txn, entities=[{"id": f"w-{gid}"}])
                result = mvcc.commit(txn)
                with lock:
                    writes[(tenant, gid)] = result["revision"]
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(("write", tenant, gid, str(exc)))

        def _reader(tenant: str, gid: str) -> None:
            try:
                mvcc = make_mvcc(holder_id=f"r-{gid}", branch_store=store)
                for _ in range(5):
                    snap = mvcc.open_snapshot(tenant, gid)
                    with lock:
                        reads.append((tenant, gid, snap.revision_id))
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    errors.append(("read", tenant, gid, str(exc)))

        threads = []
        for p in write_pairs:
            threads.append(threading.Thread(target=_writer, args=p, daemon=True))
        for p in read_pairs:
            threads.append(threading.Thread(target=_reader, args=p, daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive()

        assert not errors, errors
        assert len(writes) == len(write_pairs)
        assert len(reads) >= len(read_pairs)

        for tenant, gid in write_pairs:
            head = store.get_head(tenant, gid, "main")
            assert head != "rev-genesis"
            assert head == writes[(tenant, gid)]
        for tenant, gid in read_pairs:
            head = store.get_head(tenant, gid, "main")
            assert head == "rev-genesis"

    def test_graph_id_count_meets_acceptance_floor(self):
        """Explicit acceptance: at least 16 distinct graph IDs are exercised."""
        ids = graph_ids()
        assert len(ids) >= 16
        assert len(set(ids)) == len(ids)
