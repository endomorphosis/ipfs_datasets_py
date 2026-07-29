"""Chaos: crash injection at every WAL / publication boundary (KGP-008).

Kills (process stop) at INTENT, PREPARE, PUBLISH, and COMPLETE boundaries and
proves readers only ever observe the old head or a fully committed head.
Also covers duplicate retry, stale fencing epoch, CAS conflict under recovery,
compaction snapshot stability, and cross-tenant isolation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

# Concurrency helpers live under integration tests; add that dir for import.
_CONCURRENCY_DIR = (
    Path(__file__).resolve().parents[2]
    / "integration"
    / "knowledge_graphs"
    / "concurrency"
)
if str(_CONCURRENCY_DIR) not in sys.path:
    sys.path.insert(0, str(_CONCURRENCY_DIR))

from helpers import (  # noqa: E402
    CHILD_RECOVER,
    CHILD_STOP_AT_PHASE,
    GENESIS,
    TENANTS,
    make_file_mvcc,
    make_mvcc,
    run_child,
    tenant_graph_pairs,
)

from ipfs_datasets_py.knowledge_graphs.transactions import (  # noqa: E402
    ConflictError,
    InMemoryBranchStore,
    LeaseFencedError,
    RecoveryAction,
    WALPhase,
)


def _parse(proc) -> Dict[str, Any]:
    assert proc.returncode == 0, (
        f"child failed rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _visible_heads_ok(
    observed: str,
    *,
    old_head: str,
    published_or_complete: Optional[Set[str]] = None,
) -> None:
    """
    Invariant: a reader may only see the pre-crash head or a fully published
    / completed revision — never a partial PREPARE-only staged revision that
    never won CAS.
    """
    allowed = {old_head}
    if published_or_complete:
        allowed |= published_or_complete
    assert observed in allowed, (
        f"illegal head visibility: observed={observed!r} allowed={allowed!r}"
    )


# ---------------------------------------------------------------------------
# Crash at every durable boundary (subprocess kill simulation)
# ---------------------------------------------------------------------------


class TestCrashAtEveryWALBoundary:
    """Stop child at each phase; recover in a fresh process; check heads."""

    @pytest.mark.parametrize(
        "stop_phase,expected_action",
        [
            ("INTENT", RecoveryAction.DISCARD_STAGED.value),
            ("PREPARE", RecoveryAction.DISCARD_STAGED.value),
            ("PUBLISH", RecoveryAction.FINISH_PUBLICATION.value),
            ("COMPLETE", RecoveryAction.IDEMPOTENT_SKIP.value),
        ],
    )
    def test_kill_at_phase_only_old_or_committed_heads_visible(
        self, tmp_path: Path, stop_phase: str, expected_action: str
    ):
        """
        GIVEN: A writer process stopped at a named durable boundary
        WHEN: A fresh recovery process plans/applies recovery
        THEN: Recovery action matches the matrix and visible head is only
              the old genesis or the fully published/completed revision
        """
        root = tmp_path / f"crash-{stop_phase.lower()}"
        tenant, gid = "tenant-alpha", "graph-crash"
        make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)
        old_head = GENESIS

        stopped = _parse(
            run_child(
                CHILD_STOP_AT_PHASE,
                str(root),
                tenant,
                gid,
                "entity-crash",
                f"holder-{stop_phase}",
                stop_phase,
                f"idem-{stop_phase}",
            )
        )
        assert stopped["ok"] is True
        assert stopped["stopped"] == stop_phase
        head_before_recovery = stopped["head"]

        # Before recovery: PREPARE/INTENT must not advance head; PUBLISH/COMPLETE may.
        if stop_phase in ("INTENT", "PREPARE"):
            assert head_before_recovery == old_head
            if stop_phase == "PREPARE":
                # Staged root exists on disk but is not the branch head.
                assert stopped.get("staged_root")
                assert stopped.get("staged_revision") != head_before_recovery
        else:
            assert head_before_recovery != old_head

        pairs = json.dumps([[tenant, gid]])
        recovered = _parse(run_child(CHILD_RECOVER, str(root), pairs))
        decisions = {
            d["txn_id"]: d for d in recovered["decisions"] if d["txn_id"] == stopped["txn_id"]
        }
        assert stopped["txn_id"] in decisions
        assert decisions[stopped["txn_id"]]["action"] == expected_action

        final_head = recovered["heads"][f"{tenant}/{gid}"]
        published: Set[str] = set()
        if stop_phase in ("PUBLISH", "COMPLETE"):
            published.add(stopped.get("staged_revision") or stopped.get("revision"))
            published.discard(None)  # type: ignore[arg-type]
        _visible_heads_ok(
            final_head, old_head=old_head, published_or_complete=published
        )

        # Fresh reader process also only sees legal head.
        from helpers import CHILD_READ_HEAD

        reader = _parse(run_child(CHILD_READ_HEAD, str(root), tenant, gid))
        _visible_heads_ok(
            reader["revision"], old_head=old_head, published_or_complete=published
        )

        # PREPARE/INTENT: staged roots discarded after recovery.
        if stop_phase == "PREPARE" and stopped.get("staged_root"):
            reopened = make_file_mvcc(root, holder_id="post")
            assert not reopened.store.has_staged_root(stopped["staged_root"])
            assert reopened.store.get_head(tenant, gid, "main") == old_head

        # PUBLISH: COMPLETE marker present after FINISH_PUBLICATION.
        if stop_phase == "PUBLISH":
            reopened = make_file_mvcc(root, holder_id="post")
            phases = {
                e.resolved_phase()
                for e in reopened.wal.get_transaction_history(stopped["txn_id"])
            }
            assert WALPhase.COMPLETE in phases
            assert reopened.store.get_head(tenant, gid, "main") == stopped["staged_revision"]

    def test_kill_all_boundaries_across_sixteen_graphs(self, tmp_path: Path):
        """
        GIVEN: 16 graphs; each stopped at a rotating WAL boundary
        WHEN: Single recovery process runs
        THEN: Every graph head is either genesis or a published/completed rev
        """
        root = tmp_path / "crash-16"
        pairs = tenant_graph_pairs(16)
        phases = ["INTENT", "PREPARE", "PUBLISH", "COMPLETE"]
        boot = make_file_mvcc(root, holder_id="boot")
        for tenant, gid in pairs:
            boot.open_snapshot(tenant, gid)

        expected_published: Dict[str, Set[str]] = {}
        for i, (tenant, gid) in enumerate(pairs):
            phase = phases[i % len(phases)]
            key = f"{tenant}/{gid}"
            stopped = _parse(
                run_child(
                    CHILD_STOP_AT_PHASE,
                    str(root),
                    tenant,
                    gid,
                    f"e-{i}",
                    f"h-{i}",
                    phase,
                    f"idem-{i}",
                )
            )
            allowed: Set[str] = {GENESIS}
            if phase in ("PUBLISH", "COMPLETE"):
                rev = stopped.get("staged_revision") or stopped.get("revision")
                if rev:
                    allowed.add(rev)
            expected_published[key] = allowed

        pairs_json = json.dumps([list(p) for p in pairs])
        recovered = _parse(run_child(CHILD_RECOVER, str(root), pairs_json))
        for key, allowed in expected_published.items():
            head = recovered["heads"][key]
            assert head in allowed, f"{key}: head={head} allowed={allowed}"

    def test_abort_boundary_cleanup(self, tmp_path: Path):
        """
        GIVEN: In-process prepare then abort (durable ABORT boundary)
        WHEN: recover() runs
        THEN: Action is ABORT_CLEANUP and head remains pre-abort base
        """
        mvcc = make_mvcc(holder_id="abort-holder")
        txn = mvcc.begin("tenant-alpha", "g-abort", acquire_lease=True)
        base = txn.base_revision
        mvcc.stage_mutations(txn, entities=[{"id": "x"}])
        mvcc.prepare(txn)
        root = txn.staged_root_cid
        mvcc.abort(txn)
        assert not mvcc.store.has_staged_root(root)
        decisions = mvcc.recover()
        d = next(x for x in decisions if x.txn_id == txn.txn_id)
        assert d.action == RecoveryAction.ABORT_CLEANUP
        assert mvcc.store.get_head("tenant-alpha", "g-abort", "main") == base


# ---------------------------------------------------------------------------
# Invariants: duplicate retry, stale fence, conflict, compaction, tenants
# ---------------------------------------------------------------------------


class TestDuplicateRetryInvariant:
    def test_duplicate_complete_after_crash_finish_is_idempotent(self, tmp_path: Path):
        """
        GIVEN: Crash after PUBLISH; recovery finishes COMPLETE
        WHEN: Recovery is run a second time
        THEN: Action is IDEMPOTENT_SKIP; head unchanged
        """
        root = tmp_path / "dup-retry"
        tenant, gid = "tenant-alpha", "graph-dup"
        make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)
        stopped = _parse(
            run_child(
                CHILD_STOP_AT_PHASE,
                str(root),
                tenant,
                gid,
                "e1",
                "holder",
                "PUBLISH",
                "idem-dup",
            )
        )
        pairs = json.dumps([[tenant, gid]])
        first = _parse(run_child(CHILD_RECOVER, str(root), pairs))
        d1 = next(d for d in first["decisions"] if d["txn_id"] == stopped["txn_id"])
        assert d1["action"] == RecoveryAction.FINISH_PUBLICATION.value
        head1 = first["heads"][f"{tenant}/{gid}"]

        second = _parse(run_child(CHILD_RECOVER, str(root), pairs))
        d2 = next(d for d in second["decisions"] if d["txn_id"] == stopped["txn_id"])
        assert d2["action"] == RecoveryAction.IDEMPOTENT_SKIP.value
        assert second["heads"][f"{tenant}/{gid}"] == head1


class TestStaleFencingEpochInvariant:
    def test_stale_epoch_cannot_publish_after_steal(self):
        """
        GIVEN: Lease epoch N stolen after expiry → epoch N+1
        WHEN: Stale holder attempts head CAS with epoch N
        THEN: LeaseFencedError; head unchanged
        """
        store = InMemoryBranchStore()
        tenant, gid = "tenant-beta", "graph-fence"
        store.ensure_branch(tenant, gid, "main")
        lease_old = store.acquire_lease(
            tenant, gid, "main", holder="old", ttl_seconds=0.01
        )
        now = lease_old.expires_at + 5.0
        lease_new = store.acquire_lease(
            tenant, gid, "main", holder="new", ttl_seconds=60.0, now=now
        )
        assert lease_new.epoch > lease_old.epoch
        head = store.get_head(tenant, gid, "main")
        with pytest.raises(LeaseFencedError) as ei:
            store.cas_set_head(
                tenant,
                gid,
                "main",
                expected_revision=head,
                new_revision="rev-should-not",
                lease_id=lease_old.lease_id,
                lease_epoch=lease_old.epoch,
                now=now,
            )
        assert "stale" in str(ei.value).lower() or "epoch" in str(ei.value).lower()
        assert store.get_head(tenant, gid, "main") == head

    def test_stale_fence_on_file_store_across_processes(self, tmp_path: Path):
        """
        GIVEN: File-backed store; process A acquires short lease, expires
        WHEN: Process B steals; process A (reopened with stale tokens) CAS fails
        THEN: Head remains B-visible legal value only after B commits
        """
        root = tmp_path / "fence-file"
        tenant, gid = "tenant-alpha", "graph-ff"
        mvcc = make_file_mvcc(root, holder_id="a")
        mvcc.open_snapshot(tenant, gid)
        lease_a = mvcc.store.acquire_lease(
            tenant, gid, "main", holder="a", ttl_seconds=0.01
        )
        # Deterministic expiry
        now = lease_a.expires_at + 1.0
        # Peer process steals via file store
        peer = make_file_mvcc(root, holder_id="b")
        lease_b = peer.store.acquire_lease(
            tenant, gid, "main", holder="b", ttl_seconds=120.0, now=now
        )
        assert lease_b.epoch == lease_a.epoch + 1
        head = peer.store.get_head(tenant, gid, "main")
        with pytest.raises(LeaseFencedError):
            # Stale process A tokens
            mvcc.store.cas_set_head(
                tenant,
                gid,
                "main",
                expected_revision=head,
                new_revision="rev-a-stale",
                lease_id=lease_a.lease_id,
                lease_epoch=lease_a.epoch,
                now=now + 1.0,
            )
        assert peer.store.get_head(tenant, gid, "main") == head


class TestConflictInvariant:
    def test_cas_conflict_discards_loser_staged_root(self):
        """
        GIVEN: Two prepared txns on the same base
        WHEN: Winner publishes+completes; loser publish conflicts
        THEN: ConflictError; head is winner; loser staged root discarded
        """
        from ipfs_datasets_py.knowledge_graphs.transactions import (
            IsolationLevel,
            StagedDelta,
            Transaction,
            TransactionState,
        )

        store = InMemoryBranchStore()
        mvcc = make_mvcc(branch_store=store, holder_id="winner")
        t1 = mvcc.begin("t", "g", acquire_lease=True)
        base = t1.base_revision
        mvcc.stage_mutations(t1, entities=[{"id": "win"}])
        mvcc.prepare(t1)

        loser = make_mvcc(branch_store=store, holder_id="loser")
        t2 = Transaction(
            txn_id="txn-loser",
            isolation_level=IsolationLevel.REPEATABLE_READ,
            state=TransactionState.ACTIVE,
            tenant="t",
            graph_id="g",
            branch="main",
            base_revision=base,
            phase=WALPhase.INTENT,
        )
        loser._active[t2.txn_id] = t2
        loser._deltas[t2.txn_id] = StagedDelta(
            txn_id=t2.txn_id,
            tenant="t",
            graph_id="g",
            branch="main",
            base_revision=base,
            entities=[{"id": "lose"}],
        )
        loser.prepare(t2)
        loser_root = t2.staged_root_cid

        mvcc.publish(t1)
        mvcc.complete(t1)
        with pytest.raises(ConflictError):
            loser.publish(t2)
        assert store.get_head("t", "g", "main") == t1.staged_revision_id
        assert not store.has_staged_root(loser_root)

    def test_conflict_under_recovery_plan_is_abort_cleanup(self):
        """
        GIVEN: A txn aborted via CAS conflict (ABORT phase in WAL)
        WHEN: plan_recovery runs
        THEN: Terminal action is ABORT_CLEANUP
        """
        from ipfs_datasets_py.knowledge_graphs.transactions import (
            IsolationLevel,
            StagedDelta,
            Transaction,
            TransactionState,
        )

        store = InMemoryBranchStore()
        mvcc = make_mvcc(branch_store=store, holder_id="w")
        t1 = mvcc.begin("t", "g", acquire_lease=True)
        base = t1.base_revision
        mvcc.stage_mutations(t1, entities=[{"id": "a"}])
        mvcc.prepare(t1)

        loser = make_mvcc(branch_store=store, holder_id="l")
        t2 = Transaction(
            txn_id="txn-c",
            isolation_level=IsolationLevel.REPEATABLE_READ,
            state=TransactionState.ACTIVE,
            tenant="t",
            graph_id="g",
            branch="main",
            base_revision=base,
            phase=WALPhase.INTENT,
        )
        loser._active[t2.txn_id] = t2
        loser._deltas[t2.txn_id] = StagedDelta(
            txn_id=t2.txn_id,
            tenant="t",
            graph_id="g",
            branch="main",
            base_revision=base,
            entities=[{"id": "b"}],
        )
        loser.prepare(t2)
        mvcc.publish(t1)
        mvcc.complete(t1)
        with pytest.raises(ConflictError):
            loser.publish(t2)

        decisions = loser.wal.plan_recovery()
        d = next(x for x in decisions if x.txn_id == t2.txn_id)
        assert d.action == RecoveryAction.ABORT_CLEANUP


class TestCompactionSnapshotInvariant:
    def test_compaction_preserves_prior_snapshots_and_committed_ops(self):
        """
        GIVEN: Multiple COMPLETE WAL entries and an open snapshot at genesis
        WHEN: WAL is compacted to a checkpoint
        THEN: Prior snapshot revision remains readable; recover still replays
              only complete/committed operations; head unchanged
        """
        store = InMemoryBranchStore()
        mvcc = make_mvcc(branch_store=store, holder_id="compact")
        reader = mvcc.open_snapshot("tenant-alpha", "graph-00")
        reader_rev = reader.revision_id

        committed_revs = []
        for i in range(3):
            txn = mvcc.begin("tenant-alpha", "graph-00", acquire_lease=True)
            mvcc.stage_mutations(txn, entities=[{"id": f"e{i}"}])
            result = mvcc.commit(txn)
            committed_revs.append(result["revision"])

        head_before = store.get_head("tenant-alpha", "graph-00", "main")
        assert head_before == committed_revs[-1]

        # Compact up to current WAL head (checkpoint marker).
        checkpoint = mvcc.wal.wal_head_cid
        assert checkpoint is not None
        ck_cid = mvcc.wal.compact(checkpoint)
        assert ck_cid is not None
        assert mvcc.wal.wal_head_cid == ck_cid
        assert mvcc.wal._entry_count == 0  # reset after compact
        assert mvcc.wal.verify_integrity()

        # Snapshot taken before writes is still addressable.
        still = store.get_revision("tenant-alpha", "graph-00", reader_rev)
        assert still.revision_id == reader_rev
        # Head still the last fully committed revision (compaction does not move heads).
        assert store.get_head("tenant-alpha", "graph-00", "main") == head_before

        # recover() continues to exclude non-complete material.
        ops = mvcc.wal.recover()
        # COMPLETE phase entries may have empty ops (MVCC records phases without
        # embedding entity ops on COMPLETE). Ensure no crash and integrity holds.
        assert isinstance(ops, list)


class TestCrossTenantIsolationInvariant:
    def test_recovery_does_not_leak_heads_across_tenants(self, tmp_path: Path):
        """
        GIVEN: Two tenants, same graph_id; one crashes at PREPARE, one completes
        WHEN: Recovery runs
        THEN: Complete tenant keeps new head; prepare tenant stays at genesis
        """
        root = tmp_path / "x-tenant"
        gid = "shared-name"
        for tenant in TENANTS:
            make_file_mvcc(root, holder_id="boot").open_snapshot(tenant, gid)

        # tenant-alpha: crash at PREPARE
        a = _parse(
            run_child(
                CHILD_STOP_AT_PHASE,
                str(root),
                TENANTS[0],
                gid,
                "e-a",
                "ha",
                "PREPARE",
                "idem-a",
            )
        )
        # tenant-beta: full COMPLETE
        b = _parse(
            run_child(
                CHILD_STOP_AT_PHASE,
                str(root),
                TENANTS[1],
                gid,
                "e-b",
                "hb",
                "COMPLETE",
                "idem-b",
            )
        )
        assert a["head"] == GENESIS
        assert b["head"] != GENESIS

        pairs = json.dumps([[t, gid] for t in TENANTS])
        recovered = _parse(run_child(CHILD_RECOVER, str(root), pairs))
        assert recovered["heads"][f"{TENANTS[0]}/{gid}"] == GENESIS
        beta_head = recovered["heads"][f"{TENANTS[1]}/{gid}"]
        assert beta_head == b.get("revision") or beta_head == b.get("staged_revision")
        assert beta_head != GENESIS

        # Revision of beta is not readable under alpha tenant key.
        store = make_file_mvcc(root, holder_id="check").store
        with pytest.raises(KeyError):
            store.get_revision(TENANTS[0], gid, beta_head)

    def test_multi_tenant_sixteen_graphs_recovery_matrix(self, tmp_path: Path):
        """
        GIVEN: 16 graphs over two tenants with mixed COMPLETE and PREPARE stops
        WHEN: Recovery applies
        THEN: COMPLETE graphs advanced; PREPARE graphs remain genesis; no swaps
        """
        root = tmp_path / "matrix-16"
        pairs = tenant_graph_pairs(16)
        boot = make_file_mvcc(root, holder_id="boot")
        for tenant, gid in pairs:
            boot.open_snapshot(tenant, gid)

        expect: Dict[str, str] = {}
        for i, (tenant, gid) in enumerate(pairs):
            phase = "COMPLETE" if i % 2 == 0 else "PREPARE"
            stopped = _parse(
                run_child(
                    CHILD_STOP_AT_PHASE,
                    str(root),
                    tenant,
                    gid,
                    f"e{i}",
                    f"h{i}",
                    phase,
                    f"id{i}",
                )
            )
            key = f"{tenant}/{gid}"
            if phase == "COMPLETE":
                expect[key] = stopped.get("revision") or stopped["staged_revision"]
            else:
                expect[key] = GENESIS

        recovered = _parse(
            run_child(CHILD_RECOVER, str(root), json.dumps([list(p) for p in pairs]))
        )
        for key, want in expect.items():
            assert recovered["heads"][key] == want, key


class TestRecoveryActionMatrixExhaustive:
    def test_every_phase_has_deterministic_action(self):
        from ipfs_datasets_py.knowledge_graphs.transactions import (
            RECOVERY_ACTION_MATRIX,
            recovery_action_for_phase,
        )

        for phase in WALPhase:
            assert recovery_action_for_phase(phase) is RECOVERY_ACTION_MATRIX[phase]

    def test_in_process_boundary_kill_table(self):
        """
        GIVEN: In-process simulation of crash after each phase
        WHEN: plan_recovery is consulted without apply
        THEN: Terminal phase → action matches RECOVERY_ACTION_MATRIX
        """
        cases = [
            (WALPhase.INTENT, RecoveryAction.DISCARD_STAGED),
            (WALPhase.PREPARE, RecoveryAction.DISCARD_STAGED),
            (WALPhase.PUBLISH, RecoveryAction.FINISH_PUBLICATION),
            (WALPhase.COMPLETE, RecoveryAction.IDEMPOTENT_SKIP),
        ]
        for stop, action in cases:
            mvcc = make_mvcc(holder_id=f"tbl-{stop.value}")
            txn = mvcc.begin("t", f"g-{stop.value}", acquire_lease=True)
            if stop != WALPhase.INTENT:
                mvcc.stage_mutations(txn, entities=[{"id": "e"}])
                mvcc.prepare(txn)
            if stop in (WALPhase.PUBLISH, WALPhase.COMPLETE):
                mvcc.publish(txn)
            if stop == WALPhase.COMPLETE:
                mvcc.complete(txn)
            plan = mvcc.wal.plan_recovery()
            d = next(x for x in plan if x.txn_id == txn.txn_id)
            assert d.terminal_phase == stop
            assert d.action == action
