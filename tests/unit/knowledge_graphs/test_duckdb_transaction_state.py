"""Unit tests for fenced DuckDB transaction / MVCC state (DQK-017).

Acceptance:
- Crash recovery neither loses nor duplicates committed revisions
- Stale transaction owners are fenced
- WAL CIDs remain unchanged
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

duckdb = pytest.importorskip("duckdb")

from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError
from ipfs_datasets_py.knowledge_graphs.transactions import (
    DurableMVCC,
    IsolationLevel,
    Operation,
    OperationType,
    RecoveryAction,
    TransactionState,
    WALPhase,
    WriteAheadLog,
)
from ipfs_datasets_py.knowledge_graphs.transactions.duckdb_state import (
    DuckDBTransactionState,
    OwnerFence,
    TransactionStateError,
    create_duckdb_transaction_state,
    transaction_from_dict,
    transaction_to_dict,
)
from ipfs_datasets_py.knowledge_graphs.transactions.types import (
    StagedDelta,
    Transaction,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _InMemoryStorage:
    """Content-addressed JSON store (IPLD WAL backend stub)."""

    def __init__(self) -> None:
        self._store: Dict[str, bytes] = {}

    def store_json(self, data: dict) -> str:
        payload = json.dumps(data, sort_keys=True).encode()
        cid = "bafy" + hashlib.sha256(payload).hexdigest()[:32]
        self._store[cid] = payload
        return cid

    def retrieve_json(self, cid: str) -> dict:
        payload = self._store.get(cid)
        if payload is None:
            raise DeserializationError(f"CID not found: {cid}", details={"cid": cid})
        return json.loads(payload.decode())


def _storage() -> _InMemoryStorage:
    return _InMemoryStorage()


def _op(node_id: str = "n1") -> Operation:
    return Operation(
        type=OperationType.WRITE_NODE,
        node_id=node_id,
        data={"labels": ["Test"], "properties": {"name": node_id}},
    )


def _open_state(
    path: Path,
    *,
    owner_id: str = "owner-a",
    process_birth: str = "birth-a",
    claim_on_open: bool = True,
) -> DuckDBTransactionState:
    return DuckDBTransactionState(
        path,
        owner_id=owner_id,
        process_birth=process_birth,
        claim_on_open=claim_on_open,
    )


def _commit_one(
    state: DuckDBTransactionState,
    storage: _InMemoryStorage,
    *,
    tenant: str = "t1",
    graph_id: str = "g1",
    entity: str = "e1",
    idem: Optional[str] = "idem-1",
) -> Dict[str, Any]:
    """Run a full durable commit through DurableMVCC backed by DuckDB state."""

    wal = WriteAheadLog(storage, wal_head_cid=state.get_wal_head_cid())
    state.bind_wal(wal)
    mvcc = DurableMVCC(wal, branch_store=state, holder_id="writer-1")
    txn = mvcc.begin(
        tenant,
        graph_id,
        branch="main",
        isolation_level=IsolationLevel.REPEATABLE_READ,
        acquire_lease=True,
        idempotency_key=idem,
    )
    state.put_active_transaction(txn)
    state.note_wal_append(wal, txn.wal_entries[-1])

    mvcc.stage_operation(txn, _op(entity))
    delta = mvcc.prepare(txn)
    state.put_staged_delta(delta)
    state.put_active_transaction(txn)
    state.note_wal_append(wal, txn.wal_entries[-1])

    cas = mvcc.publish(txn)
    assert cas.success
    state.put_active_transaction(txn)
    state.note_wal_append(wal, txn.wal_entries[-1])

    result = mvcc.complete(txn)
    state.put_active_transaction(txn)
    state.note_wal_append(wal, txn.wal_entries[-1])
    state.remove_active_transaction(txn.txn_id)
    state.remove_staged_delta(txn.txn_id)
    state.record_committed_revision(
        tenant=tenant,
        graph_id=graph_id,
        branch="main",
        revision_id=result["revision"],
        parent_revision=result["parent_revision"],
        txn_id=txn.txn_id,
        wal_complete_cid=txn.wal_entries[-1],
    )
    return {
        "result": result,
        "txn": txn,
        "wal": wal,
        "revision": result["revision"],
        "complete_cid": txn.wal_entries[-1],
        "wal_head": wal.wal_head_cid,
        "wal_entries": list(txn.wal_entries),
    }


# ---------------------------------------------------------------------------
# Basic open / schema
# ---------------------------------------------------------------------------


def test_create_and_claim_owner(tmp_path: Path) -> None:
    path = tmp_path / "tx.duckdb"
    with _open_state(path, owner_id="o1", process_birth="b1") as state:
        owner = state.get_owner()
        assert owner is not None
        assert owner.owner_id == "o1"
        assert owner.generation == 1
        assert owner.process_birth == "b1"
        stats = state.get_stats()
        assert stats["schema_version"] == 1
        assert stats["owner"]["owner_id"] == "o1"


def test_factory_helper(tmp_path: Path) -> None:
    state = create_duckdb_transaction_state(
        tmp_path / "f.duckdb", owner_id="factory", process_birth="fb"
    )
    try:
        assert state.owner is not None
        assert state.owner.owner_id == "factory"
    finally:
        state.close()


# ---------------------------------------------------------------------------
# Stale transaction owners are fenced
# ---------------------------------------------------------------------------


def test_stale_transaction_owners_are_fenced(tmp_path: Path) -> None:
    path = tmp_path / "fence.duckdb"

    with _open_state(path, owner_id="owner-old", process_birth="birth-old") as old:
        gen1 = old.owner.generation
        assert gen1 == 1
        old.ensure_branch("t", "g", "main")
        # Capture the in-memory token for later stale use.
        stale_token = OwnerFence(
            owner_id=old.owner.owner_id,
            generation=old.owner.generation,
            process_birth=old.owner.process_birth,
            acquired_at=old.owner.acquired_at,
        )

    # New process claims ownership → bumps generation.
    with _open_state(path, owner_id="owner-new", process_birth="birth-new") as new:
        assert new.owner.generation == 2
        assert new.owner.owner_id == "owner-new"
        durable = new.get_owner()
        assert durable is not None
        assert durable.generation == 2

        # Simulate a stale process reattaching its old token.
        new._owner = stale_token  # noqa: SLF001 — intentional fence test
        with pytest.raises(TransactionStateError) as exc:
            new.assert_owner()
        assert exc.value.code == "FENCED"
        assert "stale" in exc.value.message.lower() or "fenced" in str(exc.value).lower()

        with pytest.raises(TransactionStateError) as exc2:
            new.ensure_branch("t", "g", "main")
        assert exc2.value.code == "FENCED"

        # Restore valid ownership and prove mutations work again.
        new._owner = durable  # noqa: SLF001
        snap = new.ensure_branch("t", "g", "main")
        assert snap.revision_id == "rev-genesis"


def test_claim_owner_bumps_generation_and_fences_previous(tmp_path: Path) -> None:
    path = tmp_path / "claim.duckdb"
    with _open_state(path, owner_id="a", process_birth="ba") as state:
        first = state.owner
        second = state.claim_owner("b", "bb")
        assert second.generation == first.generation + 1
        assert second.owner_id == "b"
        # Old token no longer valid.
        state._owner = first  # noqa: SLF001
        with pytest.raises(TransactionStateError) as exc:
            state.put_active_transaction(
                Transaction(
                    txn_id="t-x",
                    isolation_level=IsolationLevel.READ_COMMITTED,
                    state=TransactionState.ACTIVE,
                    phase=WALPhase.INTENT,
                )
            )
        assert exc.value.code == "FENCED"


# ---------------------------------------------------------------------------
# WAL CIDs remain unchanged
# ---------------------------------------------------------------------------


def test_wal_cids_remain_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "walcid.duckdb"
    storage = _storage()

    with _open_state(path) as state:
        wal = WriteAheadLog(storage)
        state.bind_wal(wal)
        state.ensure_branch("t1", "g1", "main")

        cid1 = wal.append_phase(
            txn_id="txn-wal-1",
            phase=WALPhase.INTENT,
            operations=[],
            tenant="t1",
            graph_id="g1",
            branch="main",
            base_revision="rev-genesis",
            idempotency_key="idem-wal",
            record_seq=0,
        )
        state.note_wal_append(
            wal,
            cid1,
            entry=None,
        )
        # Explicitly record the idempotent key mapping.
        replay_key = "idem:idem-wal:INTENT:0"
        state.record_wal_applied_key(replay_key, cid1)
        head1 = state.get_wal_head_cid()
        assert head1 == cid1
        assert state.get_wal_applied_key(replay_key) == cid1

        # Same phase + key → WAL returns prior CID (unchanged).
        cid2 = wal.append_phase(
            txn_id="txn-wal-1",
            phase=WALPhase.INTENT,
            operations=[],
            tenant="t1",
            graph_id="g1",
            branch="main",
            base_revision="rev-genesis",
            idempotency_key="idem-wal",
            record_seq=0,
        )
        assert cid2 == cid1

        # Re-recording same mapping is a no-op; different CID is conflict.
        state.record_wal_applied_key(replay_key, cid1)
        with pytest.raises(TransactionStateError) as exc:
            state.record_wal_applied_key(replay_key, "bafy" + ("0" * 32))
        assert exc.value.code == "CONFLICT"

        applied_before = dict(state.list_wal_applied_keys())
        head_before = state.get_wal_head_cid()

    # Survive restart: pointers and CIDs identical.
    with _open_state(path, owner_id="owner-restart", process_birth="birth-r") as state2:
        assert state2.get_wal_head_cid() == head_before
        assert state2.list_wal_applied_keys() == applied_before
        assert state2.get_wal_applied_key(replay_key) == cid1

        wal2 = WriteAheadLog(storage)
        state2.bind_wal(wal2)
        assert wal2.wal_head_cid == cid1
        assert wal2._applied_keys[replay_key] == cid1  # noqa: SLF001

        # Idempotent re-append still yields the same CID after rebind.
        cid3 = wal2.append_phase(
            txn_id="txn-wal-1",
            phase=WALPhase.INTENT,
            operations=[],
            tenant="t1",
            graph_id="g1",
            branch="main",
            base_revision="rev-genesis",
            idempotency_key="idem-wal",
            record_seq=0,
        )
        assert cid3 == cid1
        # IPLD object still intact and byte-identical.
        payload = storage.retrieve_json(cid1)
        assert payload["txn_id"] == "txn-wal-1"
        assert payload["phase"] == "INTENT"


# ---------------------------------------------------------------------------
# Crash recovery neither loses nor duplicates committed revisions
# ---------------------------------------------------------------------------


def test_crash_recovery_preserves_committed_revision_exactly_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recover-complete.duckdb"
    storage = _storage()

    with _open_state(path) as state:
        committed = _commit_one(state, storage, entity="alice", idem="idem-complete")
        rev = committed["revision"]
        head = state.get_head("t1", "g1", "main")
        assert head == rev
        revs = state.list_committed_revisions("t1", "g1", "main")
        assert revs == [rev]
        wal_head = state.get_wal_head_cid()
        assert wal_head == committed["wal_head"]
        complete_cid = committed["complete_cid"]

    # Restart + recover: must neither lose nor duplicate the committed rev.
    with _open_state(path, owner_id="owner-r1", process_birth="birth-r1") as state2:
        wal = WriteAheadLog(storage, wal_head_cid=state2.get_wal_head_cid())
        state2.bind_wal(wal)
        decisions = state2.recover(wal)
        # COMPLETE → IDEMPOTENT_SKIP (no re-CAS / no new head)
        skip_actions = [d.action for d in decisions]
        assert RecoveryAction.IDEMPOTENT_SKIP in skip_actions
        assert state2.get_head("t1", "g1", "main") == rev
        revs2 = state2.list_committed_revisions("t1", "g1", "main")
        assert revs2 == [rev], f"duplicated or lost revisions: {revs2}"

        # Second recovery is still exactly once.
        decisions2 = state2.recover(wal)
        revs3 = state2.list_committed_revisions("t1", "g1", "main")
        assert revs3 == [rev]
        assert state2.get_head("t1", "g1", "main") == rev
        # WAL complete CID still points at the original immutable entry.
        assert complete_cid in storage._store  # noqa: SLF001
        assert state2.get_wal_head_cid() is not None
        # No duplicate COMPLETE entries with different CIDs for same key.
        assert decisions2  # plan still returns the COMPLETE txn as skip


def test_crash_after_publish_finishes_once_without_duplication(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recover-publish.duckdb"
    storage = _storage()
    tenant, graph_id = "t1", "g1"

    with _open_state(path) as state:
        wal = WriteAheadLog(storage)
        state.bind_wal(wal)
        mvcc = DurableMVCC(wal, branch_store=state, holder_id="writer-pub")
        txn = mvcc.begin(tenant, graph_id, acquire_lease=True, idempotency_key="idem-pub")
        state.put_active_transaction(txn)
        state.note_wal_append(wal, txn.wal_entries[-1])

        mvcc.stage_operation(txn, _op("bob"))
        delta = mvcc.prepare(txn)
        state.put_staged_delta(delta)
        state.put_active_transaction(txn)
        state.note_wal_append(wal, txn.wal_entries[-1])

        cas = mvcc.publish(txn)
        assert cas.success
        state.put_active_transaction(txn)
        state.note_wal_append(wal, txn.wal_entries[-1])
        # Crash before complete: leave active txn + head already CAS'd.
        published_rev = txn.staged_revision_id
        assert state.get_head(tenant, graph_id, "main") == published_rev
        wal_head_before = wal.wal_head_cid

    with _open_state(path, owner_id="owner-r2", process_birth="birth-r2") as state2:
        wal2 = WriteAheadLog(storage, wal_head_cid=state2.get_wal_head_cid())
        state2.bind_wal(wal2)
        decisions = state2.recover(wal2)
        actions = {d.action for d in decisions}
        assert RecoveryAction.FINISH_PUBLICATION in actions
        assert state2.get_head(tenant, graph_id, "main") == published_rev
        revs = state2.list_committed_revisions(tenant, graph_id, "main")
        assert revs == [published_rev]

        # Second recovery: IDEMPOTENT_SKIP, still exactly one committed rev.
        decisions2 = state2.recover(wal2)
        assert any(d.action == RecoveryAction.IDEMPOTENT_SKIP for d in decisions2)
        revs2 = state2.list_committed_revisions(tenant, graph_id, "main")
        assert revs2 == [published_rev]
        # Head unchanged; no second CAS to a different revision.
        assert state2.get_head(tenant, graph_id, "main") == published_rev
        # Original publish CID still present in storage (immutable).
        assert wal_head_before in storage._store  # noqa: SLF001


def test_crash_after_prepare_discards_staged_without_head_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "recover-prepare.duckdb"
    storage = _storage()
    tenant, graph_id = "t1", "g1"

    with _open_state(path) as state:
        wal = WriteAheadLog(storage)
        state.bind_wal(wal)
        mvcc = DurableMVCC(wal, branch_store=state, holder_id="writer-prep")
        genesis = state.ensure_branch(tenant, graph_id, "main").revision_id
        txn = mvcc.begin(tenant, graph_id, acquire_lease=True)
        state.put_active_transaction(txn)
        state.note_wal_append(wal, txn.wal_entries[-1])

        mvcc.stage_operation(txn, _op("carol"))
        delta = mvcc.prepare(txn)
        state.put_staged_delta(delta)
        state.put_active_transaction(txn)
        state.note_wal_append(wal, txn.wal_entries[-1])
        staged_root = txn.staged_root_cid
        assert state.has_staged_root(staged_root)
        assert state.get_head(tenant, graph_id, "main") == genesis

    with _open_state(path, owner_id="owner-r3", process_birth="birth-r3") as state2:
        wal2 = WriteAheadLog(storage, wal_head_cid=state2.get_wal_head_cid())
        state2.bind_wal(wal2)
        decisions = state2.recover(wal2)
        assert any(d.action == RecoveryAction.DISCARD_STAGED for d in decisions)
        assert state2.get_head(tenant, graph_id, "main") == genesis
        assert not state2.has_staged_root(staged_root)
        assert state2.list_committed_revisions(tenant, graph_id, "main") == []
        assert state2.list_active_transactions() == []


# ---------------------------------------------------------------------------
# Active transaction / delta persistence
# ---------------------------------------------------------------------------


def test_active_transaction_and_delta_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "active.duckdb"
    with _open_state(path) as state:
        state.ensure_branch("t", "g", "main")
        txn = Transaction(
            txn_id="txn-persist",
            isolation_level=IsolationLevel.REPEATABLE_READ,
            state=TransactionState.ACTIVE,
            phase=WALPhase.INTENT,
            tenant="t",
            graph_id="g",
            branch="main",
            base_revision="rev-genesis",
            record_seq=1,
            wal_entries=["bafy" + ("a" * 32)],
        )
        txn.add_operation(_op("persist-node"))
        state.put_active_transaction(txn)
        delta = StagedDelta(
            txn_id="txn-persist",
            tenant="t",
            graph_id="g",
            branch="main",
            base_revision="rev-genesis",
            operations=[_op("persist-node")],
        )
        state.put_staged_delta(delta)

    with _open_state(path, owner_id="o2", process_birth="b2") as state2:
        loaded = state2.get_active_transaction("txn-persist")
        assert loaded is not None
        assert loaded.txn_id == "txn-persist"
        assert loaded.base_revision == "rev-genesis"
        assert len(loaded.operations) == 1
        assert loaded.operations[0].node_id == "persist-node"
        d2 = state2.get_staged_delta("txn-persist")
        assert d2 is not None
        assert d2.operations[0].node_id == "persist-node"


def test_transaction_dict_roundtrip() -> None:
    txn = Transaction(
        txn_id="txn-rt",
        isolation_level=IsolationLevel.SERIALIZABLE,
        state=TransactionState.PREPARED,
        phase=WALPhase.PREPARE,
        tenant="t",
        graph_id="g",
        branch="main",
        base_revision="rev-1",
        staged_revision_id="rev-2",
        staged_root_cid="staged-abc",
        lease_id="lease-1",
        lease_epoch=3,
        idempotency_key="k",
        record_seq=2,
    )
    txn.add_operation(_op("rt"))
    back = transaction_from_dict(transaction_to_dict(txn))
    assert back.txn_id == txn.txn_id
    assert back.phase == WALPhase.PREPARE
    assert back.lease_epoch == 3
    assert back.operations[0].node_id == "rt"


def test_cas_conflict_no_partial_mutation(tmp_path: Path) -> None:
    path = tmp_path / "cas.duckdb"
    with _open_state(path) as state:
        state.ensure_branch("t", "g", "main")
        state.put_revision(
            state.get_revision("t", "g", "rev-genesis")
        )
        from ipfs_datasets_py.knowledge_graphs.transactions.types import (
            SnapshotRevision,
        )
        import time

        state.put_revision(
            SnapshotRevision(
                tenant="t",
                graph_id="g",
                revision_id="rev-x",
                parent_revision="rev-genesis",
                created_at=time.time(),
            )
        )
        state.put_revision(
            SnapshotRevision(
                tenant="t",
                graph_id="g",
                revision_id="rev-y",
                parent_revision="rev-genesis",
                created_at=time.time(),
            )
        )
        lease = state.acquire_lease("t", "g", "main", holder="w", ttl_seconds=60)
        ok = state.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision="rev-genesis",
            new_revision="rev-x",
            lease_id=lease.lease_id,
            lease_epoch=lease.epoch,
        )
        assert ok.success
        bad = state.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision="rev-genesis",
            new_revision="rev-y",
            lease_id=lease.lease_id,
            lease_epoch=lease.epoch,
        )
        assert not bad.success
        assert bad.conflict
        assert state.get_head("t", "g", "main") == "rev-x"


def test_stale_lease_epoch_fenced_on_cas(tmp_path: Path) -> None:
    from ipfs_datasets_py.knowledge_graphs.transactions import LeaseFencedError

    path = tmp_path / "lease-fence.duckdb"
    with _open_state(path) as state:
        state.ensure_branch("t", "g", "main")
        lease = state.acquire_lease("t", "g", "main", holder="w1", ttl_seconds=60)
        # Steal lease with another holder after expiry simulation:
        # force-expire by re-acquiring with past expiry via direct expire.
        # Acquire as same holder renews; different holder while active fences.
        with pytest.raises(LeaseFencedError):
            state.acquire_lease("t", "g", "main", holder="w2", ttl_seconds=60)

        with pytest.raises(LeaseFencedError):
            state.cas_set_head(
                "t",
                "g",
                "main",
                expected_revision="rev-genesis",
                new_revision="rev-x",
                lease_id=lease.lease_id,
                lease_epoch=lease.epoch + 99,  # stale epoch
            )
