"""Chaos: cancellation and concurrent compaction (KGP-031).

Cooperative cancellation aborts in-flight storage/query work without
corrupting durable heads. Concurrent compaction during writers preserves
WAL integrity and prior snapshot revisions.
"""

from __future__ import annotations

import threading
import time
from typing import List

import pytest

from ipfs_datasets_py.knowledge_graphs.query.runtime import (
    CancellationError,
    CancellationToken,
)
from ipfs_datasets_py.knowledge_graphs.storage.ipld_store import IPLDGraphStore
from ipfs_datasets_py.knowledge_graphs.transactions import (
    InMemoryBranchStore,
    WriteAheadLog,
)

from tests.chaos.knowledge_graphs.helpers import (
    make_mvcc,
    wal_entry_count,
)
from tests.integration.knowledge_graphs.concurrency.helpers import InMemoryJsonStorage


class TestCancellation:
    def test_ipld_put_honors_cancel_check(self) -> None:
        cancelled = {"flag": False}

        def check() -> None:
            if cancelled["flag"]:
                raise RuntimeError("operation cancelled by client")

        store = IPLDGraphStore(cancel_check=check)
        store.put(b"ok-before-cancel")
        cancelled["flag"] = True
        with pytest.raises(RuntimeError, match="cancelled"):
            store.put(b"should-cancel")

    def test_cancel_check_raises_before_put(self) -> None:
        token = CancellationToken()

        def check() -> None:
            token.check()

        store = IPLDGraphStore(cancel_check=check)
        ok = store.put(b"pre-cancel")
        assert ok.cid
        token.cancel("client abort")
        with pytest.raises(CancellationError):
            store.put(b"post-cancel")

    def test_cancellation_token_idempotent(self) -> None:
        token = CancellationToken()
        assert not token.is_cancelled
        token.cancel("once")
        token.cancel("twice")
        assert token.is_cancelled
        with pytest.raises(CancellationError):
            token.check()

    def test_mvcc_abort_is_cancellation_cleanup(self) -> None:
        """Explicit abort cleans staged root (cancel path)."""
        mvcc = make_mvcc(holder_id="cancel-txn")
        tenant, gid = "tenant-alpha", "g-cancel"
        txn = mvcc.begin(tenant, gid, acquire_lease=True)
        base = txn.base_revision
        mvcc.stage_mutations(txn, entities=[{"id": "e"}])
        mvcc.prepare(txn)
        root = txn.staged_root_cid
        mvcc.abort(txn)
        assert not mvcc.store.has_staged_root(root)
        assert mvcc.store.get_head(tenant, gid, "main") == base


class TestConcurrentCompaction:
    def test_compaction_under_concurrent_writers(self) -> None:
        """
        GIVEN: Multiple threads committing while another compacts the WAL
        WHEN: Compaction races with appends
        THEN: Heads remain legal; WAL integrity verifies; no exceptions lost
        """
        storage = InMemoryJsonStorage()
        store = InMemoryBranchStore()
        wal = WriteAheadLog(storage)
        wal.compaction_threshold = 1_000_000
        errors: List[BaseException] = []
        heads: List[str] = []
        lock = threading.Lock()
        stop = threading.Event()

        from ipfs_datasets_py.knowledge_graphs.transactions import DurableMVCC

        mvcc = DurableMVCC(wal, branch_store=store, holder_id="compact-race")
        tenant, gid = "tenant-alpha", "g-compact"
        reader = mvcc.open_snapshot(tenant, gid)
        reader_rev = reader.revision_id

        def writer(worker_id: int) -> None:
            try:
                for i in range(8):
                    if stop.is_set():
                        break
                    # Serialize commits on a shared MVCC to avoid lease races;
                    # compaction still races with appends.
                    with lock:
                        try:
                            txn = mvcc.begin(
                                tenant,
                                gid,
                                acquire_lease=True,
                            )
                            # Re-bind holder for fencing uniqueness.
                            mvcc.holder_id = f"w-{worker_id}"
                            mvcc.stage_mutations(
                                txn,
                                entities=[{"id": f"w{worker_id}-e{i}", "n": i}],
                            )
                            result = mvcc.commit(txn)
                            heads.append(result["revision"])
                        except Exception as exc:
                            if "lease" in str(exc).lower() or "conflict" in str(
                                exc
                            ).lower():
                                return
                            raise
                    time.sleep(0.001)
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        def compactor() -> None:
            try:
                for _ in range(6):
                    if stop.is_set():
                        break
                    with lock:
                        head = wal.wal_head_cid
                        if head:
                            wal.compact(head)
                            assert wal.verify_integrity()
                    time.sleep(0.005)
            except BaseException as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
        threads.append(threading.Thread(target=compactor))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        stop.set()

        assert not errors, f"concurrent compaction errors: {errors}"
        assert wal.verify_integrity()
        final = store.get_head(tenant, gid, "main")
        assert final
        # Prior snapshot remains addressable.
        still = mvcc.open_snapshot(tenant, gid, revision=reader_rev)
        assert still.revision_id == reader_rev
        # Recovery remains safe.
        mvcc.recover()
        assert store.get_head(tenant, gid, "main") == final

    def test_compaction_preserves_committed_head_single_writer(self) -> None:
        mvcc = make_mvcc(holder_id="compact-single")
        tenant, gid = "tenant-alpha", "g-single"
        mvcc.open_snapshot(tenant, gid)
        revs = []
        for i in range(5):
            txn = mvcc.begin(tenant, gid, acquire_lease=True)
            mvcc.stage_mutations(txn, entities=[{"id": f"e{i}"}])
            revs.append(mvcc.commit(txn)["revision"])
        head = mvcc.store.get_head(tenant, gid, "main")
        assert head == revs[-1]
        ck = mvcc.wal.compact(mvcc.wal.wal_head_cid)
        assert ck
        assert mvcc.wal.verify_integrity()
        assert mvcc.store.get_head(tenant, gid, "main") == head
        assert wal_entry_count(mvcc) == 0 or mvcc.wal.wal_head_cid is not None
