"""Thread-level multi-graph / multi-tenant concurrency (KGP-008).

Exercises ≥16 graph IDs across multiple tenants with concurrent readers and
writers. No timing-only assertions — outcomes are checked via durable heads,
snapshot stability, and typed conflict/fencing results.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Tuple

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
        store = InMemoryBranchStore()
        # Shared store; each thread uses its own DurableMVCC holder id.
        pairs = tenant_graph_pairs(NUM_GRAPHS)
        assert len(pairs) >= 16
        assert {t for t, _ in pairs} == set(TENANTS)

        # Seed genesis for all pairs under a bootstrap coordinator.
        bootstrap = make_mvcc(branch_store=store, holder_id="bootstrap")
        for tenant, gid in pairs:
            bootstrap.open_snapshot(tenant, gid)

        results: Dict[Tuple[str, str], Dict[str, Any]] = {}
        errors: List[Tuple[Tuple[str, str], BaseException]] = []
        lock = threading.Lock()

        def _write(pair: Tuple[str, str]) -> None:
            tenant, gid = pair
            mvcc = make_mvcc(branch_store=store, holder_id=f"writer-{tenant}-{gid}")
            try:
                txn = mvcc.begin(tenant, gid, acquire_lease=True)
                mvcc.stage_mutations(
                    txn,
                    entities=[{"id": f"e-{tenant}-{gid}", "type": "Seed"}],
                )
                result = mvcc.commit(txn)
                with lock:
                    results[pair] = result
            except BaseException as exc:  # collect, re-raise after join
                with lock:
                    errors.append((pair, exc))

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(_write, p) for p in pairs]
            for f in as_completed(futs):
                f.result()

        assert not errors, f"writer errors: {errors}"
        assert len(results) == len(pairs)

        # Heads advanced per (tenant, graph); no cross-key clobber.
        for tenant, gid in pairs:
            head = store.get_head(tenant, gid, "main")
            assert head == results[(tenant, gid)]["revision"]
            assert head != "rev-genesis"
            snap = store.get_revision(tenant, gid, head)
            assert snap.tenant == tenant
            assert snap.graph_id == gid

    def test_readers_see_stable_snapshots_during_writes(self):
        """
        GIVEN: Readers open snapshots at genesis on 16 graphs
        WHEN: Writers commit new heads concurrently
        THEN: Reader snapshot revision_ids remain the pre-write values
        """
        store = InMemoryBranchStore()
        pairs = tenant_graph_pairs()
        mvcc = make_mvcc(branch_store=store, holder_id="coord")
        reader_revs: Dict[Tuple[str, str], str] = {}
        for tenant, gid in pairs:
            snap = mvcc.open_snapshot(tenant, gid)
            reader_revs[(tenant, gid)] = snap.revision_id

        barrier = threading.Barrier(len(pairs) + 1)

        def _writer(pair: Tuple[str, str]) -> None:
            tenant, gid = pair
            w = make_mvcc(branch_store=store, holder_id=f"w-{tenant}-{gid}")
            barrier.wait()
            txn = w.begin(tenant, gid, acquire_lease=True)
            w.stage_mutations(txn, entities=[{"id": f"n-{gid}"}])
            w.commit(txn)

        threads = [
            threading.Thread(target=_writer, args=(p,), name=f"w-{p[1]}")
            for p in pairs
        ]
        for t in threads:
            t.start()
        barrier.wait()  # release all writers together
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive()

        # Snapshots taken before the write wave are still addressable and equal
        for tenant, gid in pairs:
            rev = reader_revs[(tenant, gid)]
            still = store.get_revision(tenant, gid, rev)
            assert still.revision_id == rev
            head = store.get_head(tenant, gid, "main")
            assert head != rev  # writers advanced heads

    def test_same_graph_concurrent_writers_one_wins_cas(self):
        """
        GIVEN: Two writers on the same tenant/graph/base without exclusive lease
               for the second (CAS conflict path)
        WHEN: Both attempt publish from the same base
        THEN: Exactly one head wins; loser raises ConflictError
        """
        store = InMemoryBranchStore()
        tenant, gid = "tenant-alpha", "graph-conflict"
        mvcc_a = make_mvcc(branch_store=store, holder_id="holder-a")
        # First writer holds the lease for the branch.
        t1 = mvcc_a.begin(tenant, gid, acquire_lease=True)
        base = t1.base_revision
        mvcc_a.stage_mutations(t1, entities=[{"id": "a"}])
        mvcc_a.prepare(t1)

        # Second writer synthesizes a prepared txn on same base (no valid lease).
        from ipfs_datasets_py.knowledge_graphs.transactions import (
            IsolationLevel,
            StagedDelta,
            Transaction,
            TransactionState,
            WALPhase,
        )

        mvcc_b = make_mvcc(branch_store=store, holder_id="holder-b")
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
        for tenant, entity in (
            ("tenant-alpha", "alpha-entity"),
            ("tenant-beta", "beta-entity"),
        ):
            mvcc = make_mvcc(branch_store=store, holder_id=f"h-{tenant}")
            txn = mvcc.begin(tenant, gid, acquire_lease=True)
            mvcc.stage_mutations(txn, entities=[{"id": entity}])
            result = mvcc.commit(txn)
            assert store.get_head(tenant, gid, "main") == result["revision"]

        head_a = store.get_head("tenant-alpha", gid, "main")
        head_b = store.get_head("tenant-beta", gid, "main")
        assert head_a != head_b
        assert store.get_revision("tenant-alpha", gid, head_a).tenant == "tenant-alpha"
        assert store.get_revision("tenant-beta", gid, head_b).tenant == "tenant-beta"
        # Alpha revision is not addressable under beta key space
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
        # Deterministic expiry: advance "now" past TTL without sleep.
        now_after = lease_a.expires_at + 1.0
        lease_b = store.acquire_lease(
            tenant,
            gid,
            "main",
            holder="writer-b",
            ttl_seconds=60.0,
            now=now_after,
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
        txn = mvcc.begin("tenant-alpha", "graph-00", idempotency_key="idem-thread-1")
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        mvcc.commit(txn)
        count_before = mvcc.wal._entry_count
        history = mvcc.wal.get_transaction_history(txn.txn_id)
        complete_entries = [
            e for e in history if e.resolved_phase() == WALPhase.COMPLETE
        ]
        assert len(complete_entries) >= 1
        exact = complete_entries[0]
        prior = mvcc.wal._applied_keys[
            f"idem:{exact.idempotency_key}:COMPLETE:{exact.record_seq}"
        ]
        cid2 = mvcc.wal.append_phase(
            txn_id=exact.txn_id,
            phase=WALPhase.COMPLETE,
            idempotency_key=exact.idempotency_key,
            record_seq=exact.record_seq,
            operations=[],
        )
        assert cid2 == prior
        assert mvcc.wal._entry_count == count_before
        assert mvcc.store.get_head("tenant-alpha", "graph-00", "main") is not None


class TestMixedReadersWriters:
    def test_mixed_reader_writer_threads_across_graphs(self):
        """
        GIVEN: 16 graphs, half written and half only read concurrently
        WHEN: Threads interleave open_snapshot and commit
        THEN: All written graphs have advanced heads; read-only stay at genesis
              or their pre-existing committed revision
        """
        store = InMemoryBranchStore()
        pairs = tenant_graph_pairs()
        bootstrap = make_mvcc(branch_store=store, holder_id="boot")
        for tenant, gid in pairs:
            bootstrap.open_snapshot(tenant, gid)

        write_pairs = pairs[:8]
        read_pairs = pairs[8:]
        outcomes: Dict[str, Any] = {"writes": {}, "reads": {}, "errors": []}
        lock = threading.Lock()

        def _writer(pair: Tuple[str, str]) -> None:
            tenant, gid = pair
            try:
                mvcc = make_mvcc(branch_store=store, holder_id=f"mw-{gid}")
                txn = mvcc.begin(tenant, gid, acquire_lease=True)
                mvcc.stage_mutations(txn, entities=[{"id": f"w-{gid}"}])
                result = mvcc.commit(txn)
                with lock:
                    outcomes["writes"][f"{tenant}/{gid}"] = result["revision"]
            except BaseException as exc:
                with lock:
                    outcomes["errors"].append(("write", pair, repr(exc)))

        def _reader(pair: Tuple[str, str]) -> None:
            tenant, gid = pair
            try:
                mvcc = make_mvcc(branch_store=store, holder_id=f"mr-{gid}")
                snap = mvcc.open_snapshot(tenant, gid)
                with lock:
                    outcomes["reads"][f"{tenant}/{gid}"] = snap.revision_id
            except BaseException as exc:
                with lock:
                    outcomes["errors"].append(("read", pair, repr(exc)))

        threads: List[threading.Thread] = []
        for p in write_pairs:
            threads.append(threading.Thread(target=_writer, args=(p,)))
        for p in read_pairs:
            threads.append(threading.Thread(target=_reader, args=(p,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
            assert not t.is_alive()

        assert not outcomes["errors"], outcomes["errors"]
        assert len(outcomes["writes"]) == len(write_pairs)
        assert len(outcomes["reads"]) == len(read_pairs)
        for tenant, gid in write_pairs:
            assert store.get_head(tenant, gid, "main") != "rev-genesis"
        for tenant, gid in read_pairs:
            # Read-only graphs never received a writer in this test.
            assert store.get_head(tenant, gid, "main") == "rev-genesis"
            assert outcomes["reads"][f"{tenant}/{gid}"] == "rev-genesis"

    def test_graph_id_count_meets_acceptance_floor(self):
        """Explicit acceptance: at least 16 distinct graph IDs are exercised."""
        ids = graph_ids()
        assert len(ids) >= 16
        assert len(set(ids)) == len(ids)
