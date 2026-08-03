"""
Durable MVCC coordinator (KGP-007).

Provides:
- Snapshot revisions for stable readers
- Staged deltas invisible until publication
- Multi-phase WAL: INTENT → PREPARE → PUBLISH → COMPLETE
- Optimistic branch-head compare-and-swap
- Graph-scoped writer lease fencing
- Idempotent prepare/publish/complete and recovery replay
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .types import (
    ConflictError,
    HeadCASResult,
    IdempotencyConflictError,
    IsolationLevel,
    LeaseFence,
    LeaseFencedError,
    Operation,
    RecoveryAction,
    RecoveryDecision,
    SnapshotRevision,
    StagedDelta,
    Transaction,
    TransactionAbortedError,
    TransactionState,
    WALBoundExceededError,
    WALEntry,
    WALPhase,
    MAX_ACTIVE_TRANSACTIONS,
    MAX_STAGED_DELTA_BYTES,
    MAX_WAL_OPERATIONS_PER_ENTRY,
    phase_to_txn_state,
    recovery_action_for_phase,
)
from .wal import WriteAheadLog

logger = logging.getLogger(__name__)


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, default=str).encode("utf-8")


def _checksum(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class InMemoryBranchStore:
    """
    In-process branch head + lease + revision store for unit tests and
    embedded single-process deployments.

    Production GraphService wires catalog CAS/leases; this store implements
    the same contracts without SQLite so the MVCC layer is independently
    testable.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # (tenant, graph_id, branch) -> head revision_id
        self._heads: Dict[Tuple[str, str, str], str] = {}
        # (tenant, graph_id, revision_id) -> SnapshotRevision
        self._revisions: Dict[Tuple[str, str, str], SnapshotRevision] = {}
        # (tenant, graph_id, branch) -> LeaseFence
        self._leases: Dict[Tuple[str, str, str], LeaseFence] = {}
        # idempotency_key -> (request_hash, response_dict)
        self._idempotency: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        # staged root CIDs still considered live (discard removes them)
        self._staged_roots: Dict[str, Dict[str, Any]] = {}

    def ensure_branch(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        initial_revision: str = "rev-genesis",
    ) -> SnapshotRevision:
        with self._lock:
            key = (tenant, graph_id, branch)
            if key not in self._heads:
                snap = SnapshotRevision(
                    tenant=tenant,
                    graph_id=graph_id,
                    revision_id=initial_revision,
                    parent_revision=None,
                    root_cid=None,
                    checksum=_checksum(b"{}"),
                    created_at=time.time(),
                )
                self._heads[key] = initial_revision
                self._revisions[(tenant, graph_id, initial_revision)] = snap
            return self.get_revision(tenant, graph_id, self._heads[key])

    def get_head(self, tenant: str, graph_id: str, branch: str) -> str:
        with self._lock:
            key = (tenant, graph_id, branch)
            if key not in self._heads:
                raise KeyError(f"unknown branch {tenant}/{graph_id}/{branch}")
            return self._heads[key]

    def get_revision(
        self, tenant: str, graph_id: str, revision_id: str
    ) -> SnapshotRevision:
        with self._lock:
            key = (tenant, graph_id, revision_id)
            if key not in self._revisions:
                raise KeyError(f"unknown revision {tenant}/{graph_id}/{revision_id}")
            return self._revisions[key]

    def put_revision(self, snap: SnapshotRevision) -> None:
        with self._lock:
            self._revisions[(snap.tenant, snap.graph_id, snap.revision_id)] = snap

    def put_staged_root(self, root_cid: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._staged_roots[root_cid] = payload

    def discard_staged_root(self, root_cid: Optional[str]) -> bool:
        if not root_cid:
            return False
        with self._lock:
            return self._staged_roots.pop(root_cid, None) is not None

    def has_staged_root(self, root_cid: str) -> bool:
        with self._lock:
            return root_cid in self._staged_roots

    def cas_set_head(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        expected_revision: str,
        new_revision: str,
        lease_id: Optional[str] = None,
        lease_epoch: Optional[int] = None,
        now: Optional[float] = None,
    ) -> HeadCASResult:
        with self._lock:
            if lease_id is not None or lease_epoch is not None:
                self._check_lease(
                    tenant,
                    graph_id,
                    branch,
                    lease_id=lease_id,
                    lease_epoch=lease_epoch,
                    now=now if now is not None else time.time(),
                )
            key = (tenant, graph_id, branch)
            current = self._heads.get(key)
            if current is None:
                raise KeyError(f"unknown branch {tenant}/{graph_id}/{branch}")
            if current != expected_revision:
                return HeadCASResult(
                    success=False,
                    tenant=tenant,
                    graph_id=graph_id,
                    branch=branch,
                    expected_revision=expected_revision,
                    new_revision=new_revision,
                    current_revision=current,
                    conflict=True,
                )
            self._heads[key] = new_revision
            return HeadCASResult(
                success=True,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                expected_revision=expected_revision,
                new_revision=new_revision,
                current_revision=new_revision,
                conflict=False,
            )

    def acquire_lease(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        holder: str,
        ttl_seconds: float = 300.0,
        now: Optional[float] = None,
    ) -> LeaseFence:
        with self._lock:
            now = now if now is not None else time.time()
            key = (tenant, graph_id, branch)
            existing = self._leases.get(key)
            if existing is not None and not existing.is_expired(now):
                if existing.holder == holder:
                    # Renew in place; keep epoch for fencing continuity.
                    renewed = LeaseFence(
                        tenant=tenant,
                        graph_id=graph_id,
                        branch=branch,
                        lease_id=existing.lease_id,
                        holder=holder,
                        epoch=existing.epoch,
                        expires_at=now + float(ttl_seconds),
                        created_at=existing.created_at,
                    )
                    self._leases[key] = renewed
                    return renewed
                raise LeaseFencedError(
                    "writer lease held by another holder",
                    details={
                        "tenant": tenant,
                        "graph_id": graph_id,
                        "branch": branch,
                        "holder": holder,
                        "current_holder": existing.holder,
                        "epoch": existing.epoch,
                    },
                )
            # Steal expired or first acquire: bump fencing epoch.
            epoch = (existing.epoch + 1) if existing is not None else 1
            lease = LeaseFence(
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                lease_id=f"lease-{uuid.uuid4().hex[:12]}",
                holder=holder,
                epoch=epoch,
                expires_at=now + float(ttl_seconds),
                created_at=now,
            )
            self._leases[key] = lease
            return lease

    def _check_lease(
        self,
        tenant: str,
        graph_id: str,
        branch: str,
        *,
        lease_id: Optional[str],
        lease_epoch: Optional[int],
        now: float,
    ) -> None:
        if lease_id is None and lease_epoch is None:
            return
        if lease_id is None or lease_epoch is None:
            raise LeaseFencedError(
                "lease_id and lease_epoch must be provided together",
                details={"lease_id": lease_id, "lease_epoch": lease_epoch},
            )
        key = (tenant, graph_id, branch)
        current = self._leases.get(key)
        if current is None:
            raise LeaseFencedError(
                "no active writer lease for branch",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                },
            )
        if current.is_expired(now):
            raise LeaseFencedError(
                "writer lease expired",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                    "expires_at": current.expires_at,
                },
            )
        if current.lease_id != lease_id or int(current.epoch) != int(lease_epoch):
            raise LeaseFencedError(
                "writer lease epoch is stale",
                details={
                    "tenant": tenant,
                    "graph_id": graph_id,
                    "branch": branch,
                    "lease_id": lease_id,
                    "lease_epoch": lease_epoch,
                    "current_lease_id": current.lease_id,
                    "current_epoch": current.epoch,
                },
            )

    def check_idempotency(
        self, key: str, request_hash: str
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            prior = self._idempotency.get(key)
            if prior is None:
                return None
            prior_hash, response = prior
            if prior_hash != request_hash:
                raise IdempotencyConflictError(
                    "idempotency key reused with different request",
                    details={"key": key},
                )
            return dict(response)

    def record_idempotency(
        self, key: str, request_hash: str, response: Dict[str, Any]
    ) -> None:
        with self._lock:
            self._idempotency[key] = (request_hash, dict(response))


class DurableMVCC:
    """
    Durable multi-version concurrency control over a WriteAheadLog.

    Commit protocol (every step is a durable boundary with an exact
    recovery action — see ``RECOVERY_ACTION_MATRIX``):

    1. **INTENT**  — record intent + staged plan; crash → DISCARD_STAGED
    2. **PREPARE** — persist staged delta / revision CID; crash → DISCARD_STAGED
    3. **PUBLISH** — optimistic head CAS with lease fencing; crash →
       FINISH_PUBLICATION (idempotent COMPLETE)
    4. **COMPLETE** — mark done; crash → IDEMPOTENT_SKIP

    Readers always open an immutable :class:`SnapshotRevision`. Writers
    stage a :class:`StagedDelta` that is invisible until PUBLISH succeeds.
    """

    def __init__(
        self,
        wal: WriteAheadLog,
        *,
        branch_store: Optional[InMemoryBranchStore] = None,
        holder_id: Optional[str] = None,
        max_staged_delta_bytes: int = MAX_STAGED_DELTA_BYTES,
        max_active_transactions: int = MAX_ACTIVE_TRANSACTIONS,
    ) -> None:
        self.wal = wal
        self.store = branch_store if branch_store is not None else InMemoryBranchStore()
        self.holder_id = holder_id or f"mvcc-{uuid.uuid4().hex[:12]}"
        self.max_staged_delta_bytes = int(max_staged_delta_bytes)
        self.max_active_transactions = int(max_active_transactions)
        self._lock = threading.RLock()
        self._active: Dict[str, Transaction] = {}
        self._deltas: Dict[str, StagedDelta] = {}

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def open_snapshot(
        self,
        tenant: str,
        graph_id: str,
        *,
        branch: str = "main",
        revision: Optional[str] = None,
    ) -> SnapshotRevision:
        """
        Open an immutable snapshot for reads.

        If ``revision`` is omitted, the current branch head is used.
        The returned revision is stable for the lifetime of the reader
        even if later writers publish new heads.
        """
        self.store.ensure_branch(tenant, graph_id, branch)
        rev_id = revision or self.store.get_head(tenant, graph_id, branch)
        return self.store.get_revision(tenant, graph_id, rev_id)

    # ------------------------------------------------------------------
    # Transaction lifecycle
    # ------------------------------------------------------------------

    def begin(
        self,
        tenant: str,
        graph_id: str,
        *,
        branch: str = "main",
        isolation_level: IsolationLevel = IsolationLevel.REPEATABLE_READ,
        acquire_lease: bool = True,
        lease_ttl_seconds: float = 300.0,
        idempotency_key: Optional[str] = None,
        txn_id: Optional[str] = None,
    ) -> Transaction:
        """
        Begin a writer transaction bound to a snapshot revision.

        Optionally acquires a graph-scoped lease (fencing epoch).
        Records a durable INTENT WAL entry.
        """
        with self._lock:
            if len(self._active) >= self.max_active_transactions:
                raise WALBoundExceededError(
                    f"active transactions exceed bound {self.max_active_transactions}",
                    details={"bound": self.max_active_transactions},
                )
            if txn_id is None:
                txn_id = f"txn-{uuid.uuid4().hex[:12]}"
            if txn_id in self._active:
                raise ConflictError(
                    "transaction_id already active",
                    details={"txn_id": txn_id},
                )

            snap = self.store.ensure_branch(tenant, graph_id, branch)
            base_revision = self.store.get_head(tenant, graph_id, branch)
            lease_id = None
            lease_epoch = None
            if acquire_lease:
                lease = self.store.acquire_lease(
                    tenant,
                    graph_id,
                    branch,
                    holder=self.holder_id,
                    ttl_seconds=lease_ttl_seconds,
                )
                lease_id = lease.lease_id
                lease_epoch = lease.epoch

            txn = Transaction(
                txn_id=txn_id,
                isolation_level=isolation_level,
                state=TransactionState.ACTIVE,
                start_time=time.time(),
                snapshot_cid=snap.root_cid,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                base_revision=base_revision,
                lease_id=lease_id,
                lease_epoch=lease_epoch,
                idempotency_key=idempotency_key,
                phase=WALPhase.INTENT,
                record_seq=0,
            )
            delta = StagedDelta(
                txn_id=txn_id,
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                base_revision=base_revision,
            )
            self._active[txn_id] = txn
            self._deltas[txn_id] = delta

        # Durable INTENT boundary
        cid = self.wal.append_phase(
            txn_id=txn_id,
            phase=WALPhase.INTENT,
            operations=[],
            isolation_level=isolation_level,
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            base_revision=base_revision,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            idempotency_key=idempotency_key,
            record_seq=0,
        )
        with self._lock:
            txn.wal_entries.append(cid)
            txn.record_seq = 1
        logger.info(
            "MVCC begin txn=%s base=%s lease=%s epoch=%s",
            txn_id,
            base_revision,
            lease_id,
            lease_epoch,
        )
        return txn

    def stage_operation(self, txn: Transaction, operation: Operation) -> None:
        """Stage a single operation into the in-memory delta (pre-PREPARE)."""
        self._require_active(txn)
        with self._lock:
            txn.add_operation(operation)
            delta = self._deltas[txn.txn_id]
            delta.operations.append(operation)
            self._enforce_delta_bound(delta)

    def stage_mutations(
        self,
        txn: Transaction,
        *,
        entities: Optional[List[Dict[str, Any]]] = None,
        relationships: Optional[List[Dict[str, Any]]] = None,
        delete_entity_ids: Optional[List[str]] = None,
        operations: Optional[List[Operation]] = None,
    ) -> int:
        """Stage entity/relationship mutations into the delta."""
        self._require_active(txn)
        with self._lock:
            delta = self._deltas[txn.txn_id]
            added = 0
            for e in entities or []:
                delta.entities.append(dict(e))
                added += 1
            for r in relationships or []:
                delta.relationships.append(dict(r))
                added += 1
            for eid in delete_entity_ids or []:
                delta.delete_entity_ids.append(str(eid))
                added += 1
            for op in operations or []:
                txn.add_operation(op)
                delta.operations.append(op)
                added += 1
            self._enforce_delta_bound(delta)
            return added

    def prepare(self, txn: Transaction) -> StagedDelta:
        """
        PREPARE durable boundary: persist staged delta and record WAL PREPARE.

        Crash after PREPARE (before PUBLISH) → DISCARD_STAGED.
        """
        self._require_active(txn)
        with self._lock:
            delta = self._deltas[txn.txn_id]
            if delta.mutation_count() == 0:
                # Empty prepare is allowed (no-op commit path)
                pass
            payload = delta.to_dict()
            raw = _json_bytes(payload)
            if len(raw) > self.max_staged_delta_bytes:
                raise WALBoundExceededError(
                    f"staged delta exceeds bound {self.max_staged_delta_bytes}",
                    details={
                        "bound": self.max_staged_delta_bytes,
                        "actual": len(raw),
                        "txn_id": txn.txn_id,
                    },
                )
            staged_revision_id = (
                delta.staged_revision_id
                or f"rev-{uuid.uuid4().hex[:16]}"
            )
            root_cid = f"staged-{_checksum(raw)[:32]}"
            checksum = _checksum(raw)
            delta.staged_revision_id = staged_revision_id
            delta.staged_root_cid = root_cid
            delta.checksum = checksum
            delta.byte_size = len(raw)
            self.store.put_staged_root(root_cid, payload)
            snap = SnapshotRevision(
                tenant=txn.tenant or "",
                graph_id=txn.graph_id or "",
                revision_id=staged_revision_id,
                parent_revision=txn.base_revision,
                root_cid=root_cid,
                checksum=checksum,
                created_at=time.time(),
                metadata={"phase": "PREPARE", "txn_id": txn.txn_id},
            )
            self.store.put_revision(snap)
            txn.state = TransactionState.PREPARED
            txn.phase = WALPhase.PREPARE
            txn.staged_revision_id = staged_revision_id
            txn.staged_root_cid = root_cid
            ops = list(txn.operations)
            record_seq = txn.record_seq
            tenant = txn.tenant
            graph_id = txn.graph_id
            branch = txn.branch
            base_revision = txn.base_revision
            lease_id = txn.lease_id
            lease_epoch = txn.lease_epoch
            idem = txn.idempotency_key
            isolation = txn.isolation_level
            write_set = list(txn.write_set)
            read_set = list(txn.read_set)

        cid = self.wal.append_phase(
            txn_id=txn.txn_id,
            phase=WALPhase.PREPARE,
            operations=ops,
            isolation_level=isolation,
            read_set=read_set,
            write_set=write_set,
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            base_revision=base_revision,
            new_revision=staged_revision_id,
            staged_root_cid=root_cid,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            idempotency_key=idem,
            record_seq=record_seq,
        )
        with self._lock:
            txn.wal_entries.append(cid)
            txn.record_seq = record_seq + 1
            return self._deltas[txn.txn_id]

    def publish(self, txn: Transaction) -> HeadCASResult:
        """
        PUBLISH durable boundary: optimistic head CAS with lease fencing.

        On CAS success records WAL PUBLISH. Crash after PUBLISH
        (before COMPLETE) → FINISH_PUBLICATION.

        Raises:
            ConflictError: if head moved (CAS conflict)
            LeaseFencedError: if lease epoch is stale
            TransactionAbortedError: if not prepared
        """
        with self._lock:
            if txn.txn_id not in self._active and txn.state not in (
                TransactionState.PREPARED,
                TransactionState.PUBLISHED,
            ):
                # allow republish only if still tracked
                pass
            if txn.phase not in (WALPhase.PREPARE, WALPhase.PUBLISH):
                if txn.state not in (
                    TransactionState.PREPARED,
                    TransactionState.PUBLISHED,
                ):
                    raise TransactionAbortedError(
                        f"cannot publish from phase {txn.phase.value}",
                        details={"txn_id": txn.txn_id, "phase": txn.phase.value},
                    )
            if not txn.staged_revision_id:
                raise TransactionAbortedError(
                    "prepare required before publish",
                    details={"txn_id": txn.txn_id},
                )
            tenant = txn.tenant or ""
            graph_id = txn.graph_id or ""
            branch = txn.branch or "main"
            expected = txn.base_revision or ""
            new_rev = txn.staged_revision_id
            lease_id = txn.lease_id
            lease_epoch = txn.lease_epoch
            record_seq = txn.record_seq
            root_cid = txn.staged_root_cid
            idem = txn.idempotency_key
            isolation = txn.isolation_level

        cas = self.store.cas_set_head(
            tenant,
            graph_id,
            branch,
            expected_revision=expected,
            new_revision=new_rev,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
        )
        if not cas.success:
            with self._lock:
                txn.state = TransactionState.ABORTED
                txn.phase = WALPhase.ABORT
                self._active.pop(txn.txn_id, None)
            self.wal.append_phase(
                txn_id=txn.txn_id,
                phase=WALPhase.ABORT,
                operations=[],
                tenant=tenant,
                graph_id=graph_id,
                branch=branch,
                base_revision=expected,
                new_revision=new_rev,
                staged_root_cid=root_cid,
                lease_id=lease_id,
                lease_epoch=lease_epoch,
                idempotency_key=idem,
                record_seq=record_seq,
            )
            # Discard staged objects on conflict
            self.store.discard_staged_root(root_cid)
            raise ConflictError(
                "optimistic head CAS conflict",
                details=cas.to_dict(),
            )

        cid = self.wal.append_phase(
            txn_id=txn.txn_id,
            phase=WALPhase.PUBLISH,
            operations=[],
            isolation_level=isolation,
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            base_revision=expected,
            new_revision=new_rev,
            staged_root_cid=root_cid,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            idempotency_key=idem,
            record_seq=record_seq,
        )
        with self._lock:
            txn.state = TransactionState.PUBLISHED
            txn.phase = WALPhase.PUBLISH
            txn.wal_entries.append(cid)
            txn.record_seq = record_seq + 1
        return cas

    def complete(self, txn: Transaction) -> Dict[str, Any]:
        """
        COMPLETE durable boundary: mark transaction fully done.

        Crash after COMPLETE → IDEMPOTENT_SKIP. Safe to call twice
        with the same idempotency key (WAL append is idempotent).
        """
        with self._lock:
            if txn.phase not in (WALPhase.PUBLISH, WALPhase.COMPLETE):
                if txn.state not in (
                    TransactionState.PUBLISHED,
                    TransactionState.COMPLETE,
                    TransactionState.COMMITTED,
                ):
                    raise TransactionAbortedError(
                        f"cannot complete from phase {txn.phase.value}",
                        details={"txn_id": txn.txn_id, "phase": txn.phase.value},
                    )
            record_seq = txn.record_seq
            result = {
                "txn_id": txn.txn_id,
                "state": "COMPLETE",
                "phase": WALPhase.COMPLETE.value,
                "revision": txn.staged_revision_id,
                "parent_revision": txn.base_revision,
                "branch": txn.branch,
                "tenant": txn.tenant,
                "graph_id": txn.graph_id,
            }
            request_hash = _checksum(
                _json_bytes(
                    {
                        "txn_id": txn.txn_id,
                        "revision": txn.staged_revision_id,
                        "base": txn.base_revision,
                    }
                )
            )

        cid = self.wal.append_phase(
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
            record_seq=record_seq,
        )
        with self._lock:
            txn.state = TransactionState.COMPLETE
            txn.phase = WALPhase.COMPLETE
            txn.wal_entries.append(cid)
            self._active.pop(txn.txn_id, None)
            # Staged root becomes the published revision payload — keep it.
            if txn.idempotency_key:
                self.store.record_idempotency(
                    txn.idempotency_key, request_hash, result
                )
        return result

    def commit(self, txn: Transaction) -> Dict[str, Any]:
        """
        Full durable commit: prepare → publish → complete.

        Equivalent to the multi-phase protocol run end-to-end.
        """
        if txn.phase == WALPhase.INTENT or txn.state == TransactionState.ACTIVE:
            self.prepare(txn)
        if txn.phase == WALPhase.PREPARE or txn.state == TransactionState.PREPARED:
            self.publish(txn)
        return self.complete(txn)

    def abort(self, txn: Transaction) -> None:
        """Abort transaction; durable ABORT boundary → ABORT_CLEANUP on recovery."""
        with self._lock:
            root = txn.staged_root_cid
            tenant = txn.tenant
            graph_id = txn.graph_id
            branch = txn.branch
            base = txn.base_revision
            record_seq = txn.record_seq
            lease_id = txn.lease_id
            lease_epoch = txn.lease_epoch
            idem = txn.idempotency_key
            txn.state = TransactionState.ABORTED
            txn.phase = WALPhase.ABORT
            txn.operations.clear()
            self._active.pop(txn.txn_id, None)
            self._deltas.pop(txn.txn_id, None)

        self.store.discard_staged_root(root)
        self.wal.append_phase(
            txn_id=txn.txn_id,
            phase=WALPhase.ABORT,
            operations=[],
            tenant=tenant,
            graph_id=graph_id,
            branch=branch,
            base_revision=base,
            staged_root_cid=root,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            idempotency_key=idem,
            record_seq=record_seq,
        )

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover(self) -> List[RecoveryDecision]:
        """
        Crash recovery using exact per-boundary actions.

        - DISCARD_STAGED / ABORT_CLEANUP → drop staged roots
        - FINISH_PUBLICATION → append COMPLETE (idempotent)
        - IDEMPOTENT_SKIP → no-op
        """
        decisions = self.wal.plan_recovery()

        def _discard(decision: RecoveryDecision) -> None:
            self.store.discard_staged_root(decision.staged_root_cid)
            logger.info(
                "recovery discard staged txn=%s root=%s",
                decision.txn_id,
                decision.staged_root_cid,
            )

        def _finish(decision: RecoveryDecision) -> None:
            # Ensure head points at published revision if known
            if (
                decision.new_revision
                and decision.base_revision is not None
            ):
                # Best-effort: head may already be set; CAS only if still base.
                # We do not know tenant/graph/branch from decision alone if
                # metadata missing — history lookup fills that in.
                history = self.wal.get_transaction_history(decision.txn_id)
                tenant = graph_id = branch = None
                for e in history:
                    tenant = tenant or e.tenant
                    graph_id = graph_id or e.graph_id
                    branch = branch or e.branch
                if tenant and graph_id and branch:
                    try:
                        self.store.cas_set_head(
                            tenant,
                            graph_id,
                            branch,
                            expected_revision=decision.base_revision,
                            new_revision=decision.new_revision,
                        )
                    except (KeyError, LeaseFencedError):
                        # Head already advanced or branch missing: leave as-is.
                        pass
            logger.info(
                "recovery finish publication txn=%s rev=%s",
                decision.txn_id,
                decision.new_revision,
            )

        applied = self.wal.apply_recovery(
            decisions,
            complete_callback=_finish,
            discard_callback=_discard,
        )
        # Clear in-process active state after recovery
        with self._lock:
            self._active.clear()
            self._deltas.clear()
        return applied

    def recovery_action_for(self, phase: WALPhase) -> RecoveryAction:
        """Public accessor for the recovery matrix."""
        return recovery_action_for_phase(phase)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_active(self, txn: Transaction) -> None:
        if not txn.is_active() and txn.phase == WALPhase.INTENT:
            # allow staging only while ACTIVE/INTENT
            raise TransactionAbortedError(
                f"cannot stage on {txn.state.value} transaction",
                details={"txn_id": txn.txn_id},
            )
        if txn.state != TransactionState.ACTIVE:
            raise TransactionAbortedError(
                f"cannot stage on {txn.state.value} transaction",
                details={"txn_id": txn.txn_id},
            )

    def _enforce_delta_bound(self, delta: StagedDelta) -> None:
        if len(delta.operations) > MAX_WAL_OPERATIONS_PER_ENTRY:
            raise WALBoundExceededError(
                f"staged operations exceed bound {MAX_WAL_OPERATIONS_PER_ENTRY}",
                details={
                    "bound": MAX_WAL_OPERATIONS_PER_ENTRY,
                    "actual": len(delta.operations),
                    "txn_id": delta.txn_id,
                },
            )
        raw = _json_bytes(delta.to_dict())
        delta.byte_size = len(raw)
        if len(raw) > self.max_staged_delta_bytes:
            raise WALBoundExceededError(
                f"staged delta exceeds bound {self.max_staged_delta_bytes}",
                details={
                    "bound": self.max_staged_delta_bytes,
                    "actual": len(raw),
                    "txn_id": delta.txn_id,
                },
            )

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            active = len(self._active)
        return {
            "active_transactions": active,
            "holder_id": self.holder_id,
            "max_staged_delta_bytes": self.max_staged_delta_bytes,
            "max_active_transactions": self.max_active_transactions,
            "wal": self.wal.get_stats(),
        }


__all__ = [
    "InMemoryBranchStore",
    "DurableMVCC",
]
