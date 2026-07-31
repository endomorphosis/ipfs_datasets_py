"""
Unit tests for durable MVCC and multi-phase WAL (KGP-007).

Covers:
  - Snapshot revisions (stable readers)
  - Staged deltas (invisible until publish)
  - INTENT → PREPARE → PUBLISH → COMPLETE WAL states
  - Optimistic head CAS
  - Graph-scoped lease fencing
  - Idempotent replay
  - Exact recovery actions at every durable boundary
  - Hard bounds on WAL records
"""

from __future__ import annotations

import hashlib
import json
import time

import pytest

from ipfs_datasets_py.knowledge_graphs.transactions import (
    ConflictError,
    DurableMVCC,
    HeadCASResult,
    InMemoryBranchStore,
    IsolationLevel,
    LeaseFencedError,
    LeaseFence,
    MAX_WAL_ENTRY_BYTES,
    MAX_WAL_OPERATIONS_PER_ENTRY,
    Operation,
    OperationType,
    RECOVERY_ACTION_MATRIX,
    RecoveryAction,
    SnapshotRevision,
    StagedDelta,
    TransactionState,
    WALBoundExceededError,
    WALEntry,
    WALPhase,
    WriteAheadLog,
    phase_rank,
    recovery_action_for_phase,
)
from ipfs_datasets_py.knowledge_graphs.exceptions import DeserializationError


# ---------------------------------------------------------------------------
# Storage stub (same contract as test_wal_invariants)
# ---------------------------------------------------------------------------


class _InMemoryStorage:
    def __init__(self):
        self._store: dict = {}

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


def _wal(**kwargs) -> WriteAheadLog:
    return WriteAheadLog(_storage(), **kwargs)


def _mvcc(**kwargs) -> DurableMVCC:
    return DurableMVCC(_wal(), **kwargs)


def _op(node_id: str = "n1") -> Operation:
    return Operation(
        type=OperationType.WRITE_NODE,
        node_id=node_id,
        data={"labels": ["Test"], "properties": {"name": node_id}},
    )


# ---------------------------------------------------------------------------
# Recovery action matrix — exact at every durable boundary
# ---------------------------------------------------------------------------


class TestRecoveryActionMatrix:
    def test_matrix_covers_all_phases(self):
        """
        GIVEN: The durable WAL phases
        WHEN: Inspecting RECOVERY_ACTION_MATRIX
        THEN: Every WALPhase has an exact recovery action
        """
        for phase in WALPhase:
            assert phase in RECOVERY_ACTION_MATRIX
            assert recovery_action_for_phase(phase) is RECOVERY_ACTION_MATRIX[phase]

    def test_intent_and_prepare_discard(self):
        """Crash before publish must discard staged writes."""
        assert recovery_action_for_phase(WALPhase.INTENT) == RecoveryAction.DISCARD_STAGED
        assert recovery_action_for_phase(WALPhase.PREPARE) == RecoveryAction.DISCARD_STAGED

    def test_publish_finishes_publication(self):
        """Crash after publish must finish COMPLETE idempotently."""
        assert (
            recovery_action_for_phase(WALPhase.PUBLISH)
            == RecoveryAction.FINISH_PUBLICATION
        )

    def test_complete_is_idempotent_skip(self):
        assert (
            recovery_action_for_phase(WALPhase.COMPLETE)
            == RecoveryAction.IDEMPOTENT_SKIP
        )

    def test_abort_cleanup(self):
        assert recovery_action_for_phase(WALPhase.ABORT) == RecoveryAction.ABORT_CLEANUP

    def test_phase_rank_monotonic_for_commit_path(self):
        assert (
            phase_rank(WALPhase.INTENT)
            < phase_rank(WALPhase.PREPARE)
            < phase_rank(WALPhase.PUBLISH)
            < phase_rank(WALPhase.COMPLETE)
        )


# ---------------------------------------------------------------------------
# Snapshot revisions
# ---------------------------------------------------------------------------


class TestSnapshotRevisions:
    def test_open_snapshot_returns_immutable_revision(self):
        """
        GIVEN: A fresh MVCC store with genesis head
        WHEN: open_snapshot is called
        THEN: A SnapshotRevision with stable revision_id is returned
        """
        mvcc = _mvcc()
        snap = mvcc.open_snapshot("t1", "g1", branch="main")
        assert isinstance(snap, SnapshotRevision)
        assert snap.tenant == "t1"
        assert snap.graph_id == "g1"
        assert snap.revision_id == "rev-genesis"
        assert snap.parent_revision is None

    def test_snapshot_stable_across_later_commits(self):
        """
        GIVEN: A reader snapshot at genesis
        WHEN: A writer commits a new head
        THEN: The original snapshot revision_id is unchanged and still readable
        """
        mvcc = _mvcc()
        reader = mvcc.open_snapshot("t1", "g1")
        reader_rev = reader.revision_id

        txn = mvcc.begin("t1", "g1", acquire_lease=True)
        mvcc.stage_mutations(txn, entities=[{"id": "e1", "type": "Person"}])
        result = mvcc.commit(txn)

        # Reader revision is still the old one
        still = mvcc.open_snapshot("t1", "g1", revision=reader_rev)
        assert still.revision_id == reader_rev
        # Head advanced
        head = mvcc.open_snapshot("t1", "g1")
        assert head.revision_id == result["revision"]
        assert head.revision_id != reader_rev


# ---------------------------------------------------------------------------
# Staged deltas + multi-phase WAL
# ---------------------------------------------------------------------------


class TestStagedDeltasAndPhases:
    def test_begin_records_intent(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1")
        history = mvcc.wal.get_transaction_history(txn.txn_id)
        assert len(history) == 1
        assert history[0].resolved_phase() == WALPhase.INTENT
        assert txn.state == TransactionState.ACTIVE
        assert txn.phase == WALPhase.INTENT

    def test_staged_delta_not_visible_as_head(self):
        """
        GIVEN: A prepared (not published) transaction
        WHEN: Reading branch head
        THEN: Head remains the base revision (staged delta invisible)
        """
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1")
        base = txn.base_revision
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        delta = mvcc.prepare(txn)
        assert isinstance(delta, StagedDelta)
        assert delta.staged_root_cid is not None
        assert mvcc.store.get_head("t1", "g1", "main") == base
        assert txn.state == TransactionState.PREPARED
        assert txn.phase == WALPhase.PREPARE

    def test_prepare_publish_complete_sequence(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1", idempotency_key="idem-1")
        mvcc.stage_operation(txn, _op("n1"))
        mvcc.prepare(txn)
        cas = mvcc.publish(txn)
        assert isinstance(cas, HeadCASResult)
        assert cas.success is True
        assert txn.phase == WALPhase.PUBLISH
        result = mvcc.complete(txn)
        assert result["state"] == "COMPLETE"
        assert txn.phase == WALPhase.COMPLETE
        assert txn.state == TransactionState.COMPLETE

        phases = [e.resolved_phase() for e in mvcc.wal.get_transaction_history(txn.txn_id)]
        # Newest first
        assert WALPhase.COMPLETE in phases
        assert WALPhase.PUBLISH in phases
        assert WALPhase.PREPARE in phases
        assert WALPhase.INTENT in phases

    def test_commit_end_to_end_advances_head(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1")
        base = txn.base_revision
        mvcc.stage_mutations(
            txn,
            entities=[{"id": "e1", "type": "Person"}],
            relationships=[{"id": "r1", "type": "KNOWS"}],
        )
        result = mvcc.commit(txn)
        head = mvcc.store.get_head("t1", "g1", "main")
        assert head == result["revision"]
        assert head != base


# ---------------------------------------------------------------------------
# Optimistic head CAS
# ---------------------------------------------------------------------------


class TestOptimisticHeadCAS:
    def test_cas_conflict_on_concurrent_publish(self):
        """
        GIVEN: Two transactions prepared from the same base
        WHEN: First publish succeeds and second publish attempts CAS
        THEN: Second raises ConflictError and head stays at first winner
        """
        store = InMemoryBranchStore()
        wal = WriteAheadLog(_storage())
        mvcc = DurableMVCC(wal, branch_store=store, holder_id="h1")

        # First writer holds lease
        t1 = mvcc.begin("t1", "g1", acquire_lease=True)
        mvcc.stage_mutations(t1, entities=[{"id": "a"}])
        mvcc.prepare(t1)

        # Second writer on same base without lease (concurrent CAS loser).
        from ipfs_datasets_py.knowledge_graphs.transactions.types import Transaction

        t2_txn = Transaction(
            txn_id="txn-second",
            isolation_level=IsolationLevel.REPEATABLE_READ,
            state=TransactionState.ACTIVE,
            tenant="t1",
            graph_id="g1",
            branch="main",
            base_revision=t1.base_revision,
            phase=WALPhase.INTENT,
        )
        mvcc._active[t2_txn.txn_id] = t2_txn
        mvcc._deltas[t2_txn.txn_id] = StagedDelta(
            txn_id=t2_txn.txn_id,
            tenant="t1",
            graph_id="g1",
            branch="main",
            base_revision=t1.base_revision,
            entities=[{"id": "b"}],
        )
        mvcc.prepare(t2_txn)

        # Winner publishes with valid lease
        cas1 = mvcc.publish(t1)
        assert cas1.success
        mvcc.complete(t1)

        # Loser: same expected base, no lease → CAS conflict
        with pytest.raises(ConflictError) as ei:
            mvcc.publish(t2_txn)
        assert ei.value.details.get("conflict") is True
        assert store.get_head("t1", "g1", "main") == t1.staged_revision_id

    def test_branch_store_cas_direct(self):
        store = InMemoryBranchStore()
        store.ensure_branch("t", "g", "main")
        head = store.get_head("t", "g", "main")
        ok = store.cas_set_head(
            "t", "g", "main", expected_revision=head, new_revision="rev-2"
        )
        assert ok.success
        bad = store.cas_set_head(
            "t", "g", "main", expected_revision=head, new_revision="rev-3"
        )
        assert bad.success is False
        assert bad.conflict is True
        assert store.get_head("t", "g", "main") == "rev-2"


# ---------------------------------------------------------------------------
# Graph-scoped lease fencing
# ---------------------------------------------------------------------------


class TestLeaseFencing:
    def test_acquire_lease_assigns_epoch(self):
        store = InMemoryBranchStore()
        store.ensure_branch("t", "g", "main")
        lease = store.acquire_lease("t", "g", "main", holder="w1", ttl_seconds=60)
        assert isinstance(lease, LeaseFence)
        assert lease.epoch == 1
        assert lease.holder == "w1"

    def test_stale_epoch_is_fenced(self):
        store = InMemoryBranchStore()
        store.ensure_branch("t", "g", "main")
        lease = store.acquire_lease("t", "g", "main", holder="w1", ttl_seconds=0.01)
        time.sleep(0.02)
        # New holder steals expired lease → epoch bumps
        lease2 = store.acquire_lease("t", "g", "main", holder="w2", ttl_seconds=60)
        assert lease2.epoch == lease.epoch + 1
        head = store.get_head("t", "g", "main")
        with pytest.raises(LeaseFencedError):
            store.cas_set_head(
                "t",
                "g",
                "main",
                expected_revision=head,
                new_revision="rev-x",
                lease_id=lease.lease_id,
                lease_epoch=lease.epoch,
            )

    def test_matching_lease_allows_cas(self):
        store = InMemoryBranchStore()
        store.ensure_branch("t", "g", "main")
        lease = store.acquire_lease("t", "g", "main", holder="w1", ttl_seconds=60)
        head = store.get_head("t", "g", "main")
        cas = store.cas_set_head(
            "t",
            "g",
            "main",
            expected_revision=head,
            new_revision="rev-ok",
            lease_id=lease.lease_id,
            lease_epoch=lease.epoch,
        )
        assert cas.success

    def test_renew_same_holder_keeps_epoch(self):
        store = InMemoryBranchStore()
        store.ensure_branch("t", "g", "main")
        l1 = store.acquire_lease("t", "g", "main", holder="w1", ttl_seconds=60)
        l2 = store.acquire_lease("t", "g", "main", holder="w1", ttl_seconds=60)
        assert l1.epoch == l2.epoch
        assert l1.lease_id == l2.lease_id


# ---------------------------------------------------------------------------
# Idempotent replay
# ---------------------------------------------------------------------------


class TestIdempotentReplay:
    def test_duplicate_phase_append_returns_same_cid(self):
        wal = _wal()
        cid1 = wal.append_phase(
            txn_id="txn-a",
            phase=WALPhase.COMPLETE,
            idempotency_key="k1",
            operations=[],
            record_seq=1,
        )
        cid2 = wal.append_phase(
            txn_id="txn-a",
            phase=WALPhase.COMPLETE,
            idempotency_key="k1",
            operations=[],
            record_seq=1,
        )
        assert cid1 == cid2
        # Only one physical entry (second was idempotent skip)
        assert wal._entry_count == 1

    def test_recover_complete_is_idempotent_skip(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1", idempotency_key="idem-complete")
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        mvcc.commit(txn)
        decisions = mvcc.recover()
        # The completed txn should be IDEMPOTENT_SKIP
        by_id = {d.txn_id: d for d in decisions}
        assert by_id[txn.txn_id].action == RecoveryAction.IDEMPOTENT_SKIP

    def test_complete_twice_via_wal_idempotency(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1", idempotency_key="idem-2")
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        mvcc.prepare(txn)
        mvcc.publish(txn)
        r1 = mvcc.complete(txn)
        # Force phase back and complete again — WAL COMPLETE is idempotent
        txn.phase = WALPhase.PUBLISH
        txn.state = TransactionState.PUBLISHED
        r2 = mvcc.complete(txn)
        assert r1["revision"] == r2["revision"]


# ---------------------------------------------------------------------------
# Recovery at every durable boundary
# ---------------------------------------------------------------------------


class TestRecoveryBoundaries:
    def test_crash_after_intent_discards(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1")
        # Stop at INTENT (no prepare)
        decisions = mvcc.wal.plan_recovery()
        d = next(x for x in decisions if x.txn_id == txn.txn_id)
        assert d.terminal_phase == WALPhase.INTENT
        assert d.action == RecoveryAction.DISCARD_STAGED
        mvcc.recover()
        # Head unchanged
        assert mvcc.store.get_head("t1", "g1", "main") == txn.base_revision

    def test_crash_after_prepare_discards_staged_root(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1")
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        delta = mvcc.prepare(txn)
        root = delta.staged_root_cid
        assert mvcc.store.has_staged_root(root)
        decisions = mvcc.wal.plan_recovery()
        d = next(x for x in decisions if x.txn_id == txn.txn_id)
        assert d.action == RecoveryAction.DISCARD_STAGED
        mvcc.recover()
        assert not mvcc.store.has_staged_root(root)
        assert mvcc.store.get_head("t1", "g1", "main") == txn.base_revision

    def test_crash_after_publish_finishes_complete(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1")
        base = txn.base_revision
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        mvcc.prepare(txn)
        mvcc.publish(txn)
        # Head already advanced; COMPLETE missing
        assert mvcc.store.get_head("t1", "g1", "main") == txn.staged_revision_id
        decisions = mvcc.wal.plan_recovery()
        d = next(x for x in decisions if x.txn_id == txn.txn_id)
        assert d.action == RecoveryAction.FINISH_PUBLICATION
        mvcc.recover()
        # COMPLETE marker present
        phases = {
            e.resolved_phase() for e in mvcc.wal.get_transaction_history(txn.txn_id)
        }
        assert WALPhase.COMPLETE in phases
        # Head still the published revision (not rolled back)
        assert mvcc.store.get_head("t1", "g1", "main") == txn.staged_revision_id
        assert mvcc.store.get_head("t1", "g1", "main") != base

    def test_crash_after_complete_skips(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1")
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        mvcc.commit(txn)
        head_before = mvcc.store.get_head("t1", "g1", "main")
        applied = mvcc.recover()
        d = next(x for x in applied if x.txn_id == txn.txn_id)
        assert d.action == RecoveryAction.IDEMPOTENT_SKIP
        assert mvcc.store.get_head("t1", "g1", "main") == head_before

    def test_abort_recovery_cleanup(self):
        mvcc = _mvcc()
        txn = mvcc.begin("t1", "g1")
        mvcc.stage_mutations(txn, entities=[{"id": "e1"}])
        mvcc.prepare(txn)
        root = txn.staged_root_cid
        mvcc.abort(txn)
        assert not mvcc.store.has_staged_root(root)
        decisions = mvcc.wal.plan_recovery()
        d = next(x for x in decisions if x.txn_id == txn.txn_id)
        assert d.action == RecoveryAction.ABORT_CLEANUP


# ---------------------------------------------------------------------------
# Bound WAL records
# ---------------------------------------------------------------------------


class TestWALBounds:
    def test_operations_bound_rejected(self):
        wal = WriteAheadLog(_storage(), max_operations_per_entry=3)
        ops = [_op(f"n{i}") for i in range(5)]
        entry = WALEntry(
            txn_id="txn-big",
            timestamp=time.time(),
            operations=ops,
            txn_state=TransactionState.COMMITTED,
        )
        with pytest.raises(WALBoundExceededError) as ei:
            wal.append(entry)
        assert ei.value.details["bound_kind"] == "operations"

    def test_entry_bytes_bound_rejected(self):
        wal = WriteAheadLog(_storage(), max_entry_bytes=200)
        # Fat operation payload
        fat = Operation(
            type=OperationType.WRITE_NODE,
            node_id="n1",
            data={"blob": "x" * 500},
        )
        entry = WALEntry(
            txn_id="txn-fat",
            timestamp=time.time(),
            operations=[fat],
            txn_state=TransactionState.COMMITTED,
        )
        with pytest.raises(WALBoundExceededError) as ei:
            wal.append(entry)
        assert ei.value.details["bound_kind"] == "entry_bytes"

    def test_write_set_bound_rejected(self):
        wal = WriteAheadLog(_storage(), max_write_set_size=2)
        entry = WALEntry(
            txn_id="txn-ws",
            timestamp=time.time(),
            operations=[_op()],
            txn_state=TransactionState.COMMITTED,
            write_set=["a", "b", "c"],
        )
        with pytest.raises(WALBoundExceededError) as ei:
            wal.append(entry)
        assert ei.value.details["bound_kind"] == "write_set"

    def test_staged_delta_bound_on_prepare(self):
        mvcc = DurableMVCC(
            _wal(),
            max_staged_delta_bytes=300,
        )
        txn = mvcc.begin("t1", "g1")
        # Bound is enforced when the staged delta is mutated or prepared.
        with pytest.raises(WALBoundExceededError):
            mvcc.stage_mutations(
                txn,
                entities=[{"id": "e1", "payload": "y" * 400}],
            )
            mvcc.prepare(txn)

    def test_stats_expose_bounds(self):
        wal = _wal()
        stats = wal.get_stats()
        assert stats["max_operations_per_entry"] == MAX_WAL_OPERATIONS_PER_ENTRY
        assert stats["max_entry_bytes"] == MAX_WAL_ENTRY_BYTES
        assert "recovery_matrix" in stats
        assert stats["recovery_matrix"]["PREPARE"] == "DISCARD_STAGED"


# ---------------------------------------------------------------------------
# Types serialization round-trip
# ---------------------------------------------------------------------------


class TestTypeRoundTrip:
    def test_wal_entry_phase_round_trip(self):
        entry = WALEntry(
            txn_id="txn-rt",
            timestamp=1234.5,
            operations=[_op()],
            txn_state=TransactionState.PREPARED,
            phase=WALPhase.PREPARE,
            tenant="t",
            graph_id="g",
            branch="main",
            base_revision="rev-0",
            new_revision="rev-1",
            staged_root_cid="staged-abc",
            lease_id="lease-1",
            lease_epoch=2,
            idempotency_key="k",
            record_seq=3,
        )
        restored = WALEntry.from_dict(entry.to_dict())
        assert restored.phase == WALPhase.PREPARE
        assert restored.lease_epoch == 2
        assert restored.resolved_phase() == WALPhase.PREPARE
        assert restored.staged_root_cid == "staged-abc"

    def test_snapshot_revision_round_trip(self):
        snap = SnapshotRevision(
            tenant="t",
            graph_id="g",
            revision_id="rev-1",
            parent_revision="rev-0",
            root_cid="cid-1",
            checksum="abc",
            created_at=1.0,
            metadata={"k": "v"},
        )
        assert SnapshotRevision.from_dict(snap.to_dict()) == snap

    def test_legacy_committed_without_phase_maps_to_complete(self):
        entry = WALEntry(
            txn_id="legacy",
            timestamp=1.0,
            operations=[_op()],
            txn_state=TransactionState.COMMITTED,
        )
        assert entry.resolved_phase() == WALPhase.COMPLETE


# ---------------------------------------------------------------------------
# WAL recover() still replays only complete/committed
# ---------------------------------------------------------------------------


class TestLegacyRecoverCompatibility:
    def test_recover_includes_complete_and_committed_only(self):
        wal = _wal()
        wal.append_phase(
            txn_id="t-prep",
            phase=WALPhase.PREPARE,
            operations=[_op("p1")],
            timestamp=1000.0,
        )
        wal.append_phase(
            txn_id="t-done",
            phase=WALPhase.COMPLETE,
            operations=[_op("c1"), _op("c2")],
            timestamp=1001.0,
        )
        # Legacy COMMITTED
        wal.append(
            WALEntry(
                txn_id="t-legacy",
                timestamp=1002.0,
                operations=[_op("l1")],
                txn_state=TransactionState.COMMITTED,
            )
        )
        ops = wal.recover()
        # PREPARE excluded; COMPLETE + COMMITTED included
        node_ids = [o.node_id for o in ops]
        assert "p1" not in node_ids
        assert "c1" in node_ids
        assert "c2" in node_ids
        assert "l1" in node_ids
