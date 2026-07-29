"""
Transaction Type Definitions

Defines data structures for the durable MVCC / WAL transaction system:
snapshot revisions, staged deltas, prepare/publish/complete WAL phases,
optimistic head CAS, graph-scoped lease fencing, and recovery actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


# ---------------------------------------------------------------------------
# Bounds for WAL records (hard limits; reject oversized writes)
# ---------------------------------------------------------------------------

# Maximum operations stored inline in a single WAL entry.
MAX_WAL_OPERATIONS_PER_ENTRY: int = 10_000

# Maximum serialized JSON size (UTF-8 bytes) for one WAL entry payload.
MAX_WAL_ENTRY_BYTES: int = 4 * 1024 * 1024  # 4 MiB

# Maximum entity IDs in a transaction write/read set.
MAX_WRITE_SET_SIZE: int = 100_000
MAX_READ_SET_SIZE: int = 100_000

# Maximum serialized staged delta payload.
MAX_STAGED_DELTA_BYTES: int = 8 * 1024 * 1024  # 8 MiB

# Maximum concurrent active staged transactions tracked in-process.
MAX_ACTIVE_TRANSACTIONS: int = 10_000


class IsolationLevel(Enum):
    """
    Transaction isolation levels matching Neo4j semantics.

    Attributes:
        READ_UNCOMMITTED: No isolation, can read uncommitted changes (not recommended)
        READ_COMMITTED: Can only read committed changes
        REPEATABLE_READ: Snapshot isolation, sees consistent snapshot (default)
        SERIALIZABLE: Full serializability, prevents all anomalies
    """

    READ_UNCOMMITTED = "READ_UNCOMMITTED"
    READ_COMMITTED = "READ_COMMITTED"
    REPEATABLE_READ = "REPEATABLE_READ"
    SERIALIZABLE = "SERIALIZABLE"


class TransactionState(Enum):
    """
    Transaction lifecycle states including durable multi-phase commit.

    Durable commit protocol states (KGP-007):
        ACTIVE    — accepting operations / staging deltas in memory
        PREPARING — legacy alias for prepare-in-progress
        PREPARED  — prepare durable (staged objects reachable by CID)
        PUBLISHED — head publication durable (CAS recorded)
        COMPLETE  — fully complete; safe for readers and compaction
        COMMITTED — legacy synonym for COMPLETE (replayed by recover())
        ABORTED   — rolled back; staged objects unreachable
        FAILED    — failed due to error
    """

    ACTIVE = "ACTIVE"
    PREPARING = "PREPARING"
    PREPARED = "PREPARED"
    PUBLISHED = "PUBLISHED"
    COMPLETE = "COMPLETE"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


class WALPhase(Enum):
    """
    Durable WAL phase markers at each crash-recovery boundary.

    INTENT   — transaction intent + staged plan recorded (not published)
    PREPARE  — prepared objects durable (staged revision/delta CID known)
    PUBLISH  — branch head CAS recorded / publication durable
    COMPLETE — commit fully finished; idempotent replay is a no-op
    ABORT    — explicit abort recorded
    """

    INTENT = "INTENT"
    PREPARE = "PREPARE"
    PUBLISH = "PUBLISH"
    COMPLETE = "COMPLETE"
    ABORT = "ABORT"


class RecoveryAction(Enum):
    """
    Exact recovery action at each durable WAL boundary.

    DISCARD_STAGED      — INTENT only (or PREPARE without publish): drop staged
                          objects; never expose partial head.
    FINISH_PUBLICATION  — PUBLISH without COMPLETE: finish complete marker and
                          ensure head is the published revision (idempotent).
    IDEMPOTENT_SKIP     — COMPLETE/COMMITTED already applied or idempotency hit.
    ABORT_CLEANUP       — ABORT: ensure staged objects remain unreachable.
    NOOP                — nothing required (empty log, already clean).
    """

    DISCARD_STAGED = "DISCARD_STAGED"
    FINISH_PUBLICATION = "FINISH_PUBLICATION"
    IDEMPOTENT_SKIP = "IDEMPOTENT_SKIP"
    ABORT_CLEANUP = "ABORT_CLEANUP"
    NOOP = "NOOP"


class OperationType(Enum):
    """
    Types of operations that can be recorded in WAL.

    Attributes:
        WRITE_NODE: Create or update a node
        WRITE_RELATIONSHIP: Create or update a relationship
        DELETE_NODE: Delete a node
        DELETE_RELATIONSHIP: Delete a relationship
        SET_PROPERTY: Set a property on node/relationship
        REMOVE_PROPERTY: Remove a property from node/relationship
    """

    WRITE_NODE = "WRITE_NODE"
    WRITE_RELATIONSHIP = "WRITE_RELATIONSHIP"
    DELETE_NODE = "DELETE_NODE"
    DELETE_RELATIONSHIP = "DELETE_RELATIONSHIP"
    SET_PROPERTY = "SET_PROPERTY"
    REMOVE_PROPERTY = "REMOVE_PROPERTY"


@dataclass
class Operation:
    """
    A single operation within a transaction.

    Stored in WAL entries and replayed during recovery.

    Attributes:
        type: Type of operation
        node_id: ID of affected node (if applicable)
        rel_id: ID of affected relationship (if applicable)
        data: Operation-specific data (node/rel properties, etc.)
        prev_cid: Previous CID of affected entity (for versioning)
    """

    type: OperationType
    node_id: Optional[str] = None
    rel_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    prev_cid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert operation to dictionary for storage."""
        return {
            "type": self.type.value,
            "node_id": self.node_id,
            "rel_id": self.rel_id,
            "data": self.data,
            "prev_cid": self.prev_cid,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Operation":
        """Create operation from dictionary."""
        return cls(
            type=OperationType(data["type"]),
            node_id=data.get("node_id"),
            rel_id=data.get("rel_id"),
            data=data.get("data"),
            prev_cid=data.get("prev_cid"),
        )


@dataclass(frozen=True)
class SnapshotRevision:
    """
    Immutable point-in-time graph revision for snapshot reads.

    Readers bind to a revision; writers never mutate a published revision
    in place. Compaction must not invalidate existing snapshots.
    """

    tenant: str
    graph_id: str
    revision_id: str
    parent_revision: Optional[str] = None
    root_cid: Optional[str] = None
    checksum: Optional[str] = None
    created_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "revision_id": self.revision_id,
            "parent_revision": self.parent_revision,
            "root_cid": self.root_cid,
            "checksum": self.checksum,
            "created_at": self.created_at,
            "metadata": dict(self.metadata) if self.metadata else {},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SnapshotRevision":
        return cls(
            tenant=str(data["tenant"]),
            graph_id=str(data["graph_id"]),
            revision_id=str(data["revision_id"]),
            parent_revision=data.get("parent_revision"),
            root_cid=data.get("root_cid"),
            checksum=data.get("checksum"),
            created_at=float(data.get("created_at") or 0.0),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class StagedDelta:
    """
    Writer-staged delta that is not yet published as a branch head.

    Staged objects become durable at PREPARE. They remain invisible to
    readers until PUBLISH succeeds (optimistic head CAS).
    """

    txn_id: str
    tenant: str
    graph_id: str
    branch: str
    base_revision: str
    operations: List[Operation] = field(default_factory=list)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    delete_entity_ids: List[str] = field(default_factory=list)
    staged_revision_id: Optional[str] = None
    staged_root_cid: Optional[str] = None
    checksum: Optional[str] = None
    byte_size: int = 0

    def mutation_count(self) -> int:
        return (
            len(self.operations)
            + len(self.entities)
            + len(self.relationships)
            + len(self.delete_entity_ids)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "txn_id": self.txn_id,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "base_revision": self.base_revision,
            "operations": [op.to_dict() for op in self.operations],
            "entities": list(self.entities),
            "relationships": list(self.relationships),
            "delete_entity_ids": list(self.delete_entity_ids),
            "staged_revision_id": self.staged_revision_id,
            "staged_root_cid": self.staged_root_cid,
            "checksum": self.checksum,
            "byte_size": self.byte_size,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StagedDelta":
        return cls(
            txn_id=str(data["txn_id"]),
            tenant=str(data["tenant"]),
            graph_id=str(data["graph_id"]),
            branch=str(data["branch"]),
            base_revision=str(data["base_revision"]),
            operations=[Operation.from_dict(o) for o in data.get("operations") or []],
            entities=list(data.get("entities") or []),
            relationships=list(data.get("relationships") or []),
            delete_entity_ids=list(data.get("delete_entity_ids") or []),
            staged_revision_id=data.get("staged_revision_id"),
            staged_root_cid=data.get("staged_root_cid"),
            checksum=data.get("checksum"),
            byte_size=int(data.get("byte_size") or 0),
        )


@dataclass(frozen=True)
class LeaseFence:
    """Graph-scoped writer lease with fencing epoch."""

    tenant: str
    graph_id: str
    branch: str
    lease_id: str
    holder: str
    epoch: int
    expires_at: float
    created_at: float = 0.0

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "lease_id": self.lease_id,
            "holder": self.holder,
            "epoch": self.epoch,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LeaseFence":
        return cls(
            tenant=str(data["tenant"]),
            graph_id=str(data["graph_id"]),
            branch=str(data["branch"]),
            lease_id=str(data["lease_id"]),
            holder=str(data["holder"]),
            epoch=int(data["epoch"]),
            expires_at=float(data["expires_at"]),
            created_at=float(data.get("created_at") or 0.0),
        )


@dataclass(frozen=True)
class HeadCASResult:
    """Outcome of an optimistic branch-head compare-and-swap."""

    success: bool
    tenant: str
    graph_id: str
    branch: str
    expected_revision: str
    new_revision: str
    current_revision: str
    conflict: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "tenant": self.tenant,
            "graph_id": self.graph_id,
            "branch": self.branch,
            "expected_revision": self.expected_revision,
            "new_revision": self.new_revision,
            "current_revision": self.current_revision,
            "conflict": self.conflict,
        }


@dataclass(frozen=True)
class RecoveryDecision:
    """
    Recovery decision for one transaction at a durable boundary.

    Attributes:
        txn_id: Transaction identifier
        terminal_phase: Highest durable phase observed for the txn
        action: Exact recovery action to take
        base_revision: Snapshot base (if known)
        new_revision: Staged/published revision (if known)
        staged_root_cid: Staged payload CID (if known)
        reason: Human-readable rationale
    """

    txn_id: str
    terminal_phase: WALPhase
    action: RecoveryAction
    base_revision: Optional[str] = None
    new_revision: Optional[str] = None
    staged_root_cid: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "txn_id": self.txn_id,
            "terminal_phase": self.terminal_phase.value,
            "action": self.action.value,
            "base_revision": self.base_revision,
            "new_revision": self.new_revision,
            "staged_root_cid": self.staged_root_cid,
            "reason": self.reason,
        }


# Recovery action matrix: terminal durable phase → recovery action.
# Defined exactly so crash recovery is deterministic.
RECOVERY_ACTION_MATRIX: Dict[WALPhase, RecoveryAction] = {
    WALPhase.INTENT: RecoveryAction.DISCARD_STAGED,
    WALPhase.PREPARE: RecoveryAction.DISCARD_STAGED,
    WALPhase.PUBLISH: RecoveryAction.FINISH_PUBLICATION,
    WALPhase.COMPLETE: RecoveryAction.IDEMPOTENT_SKIP,
    WALPhase.ABORT: RecoveryAction.ABORT_CLEANUP,
}


def recovery_action_for_phase(phase: WALPhase) -> RecoveryAction:
    """Return the exact recovery action for a terminal durable phase."""
    return RECOVERY_ACTION_MATRIX[phase]


def phase_rank(phase: WALPhase) -> int:
    """Monotonic rank for durable phases (higher = later in protocol)."""
    order = {
        WALPhase.INTENT: 1,
        WALPhase.PREPARE: 2,
        WALPhase.PUBLISH: 3,
        WALPhase.COMPLETE: 4,
        WALPhase.ABORT: 0,
    }
    return order[phase]


def txn_state_to_phase(state: TransactionState) -> Optional[WALPhase]:
    """Map transaction state to durable WAL phase when applicable."""
    mapping = {
        TransactionState.ACTIVE: WALPhase.INTENT,
        TransactionState.PREPARING: WALPhase.PREPARE,
        TransactionState.PREPARED: WALPhase.PREPARE,
        TransactionState.PUBLISHED: WALPhase.PUBLISH,
        TransactionState.COMPLETE: WALPhase.COMPLETE,
        TransactionState.COMMITTED: WALPhase.COMPLETE,
        TransactionState.ABORTED: WALPhase.ABORT,
        TransactionState.FAILED: WALPhase.ABORT,
    }
    return mapping.get(state)


def phase_to_txn_state(phase: WALPhase) -> TransactionState:
    """Map durable WAL phase to transaction state for storage."""
    mapping = {
        WALPhase.INTENT: TransactionState.ACTIVE,
        WALPhase.PREPARE: TransactionState.PREPARED,
        WALPhase.PUBLISH: TransactionState.PUBLISHED,
        WALPhase.COMPLETE: TransactionState.COMPLETE,
        WALPhase.ABORT: TransactionState.ABORTED,
    }
    return mapping[phase]


@dataclass
class WALEntry:
    """
    Write-Ahead Log entry stored on IPLD / durable storage.

    Each transaction creates a chain of WAL entries linked by CIDs.
    WAL entries are immutable and form an append-only log.

    Multi-phase durable commit (KGP-007) records INTENT → PREPARE →
    PUBLISH → COMPLETE (or ABORT). Recovery uses the terminal phase
    to choose an exact action from RECOVERY_ACTION_MATRIX.

    Attributes:
        txn_id: Unique transaction identifier
        timestamp: Unix timestamp when entry was created
        operations: List of operations in this entry
        prev_wal_cid: CID of previous WAL entry (forms chain)
        txn_state: Current state of the transaction
        isolation_level: Isolation level for this transaction
        read_set: Set of CIDs read by transaction (for conflict detection)
        write_set: Set of entity IDs written by transaction
        phase: Durable WAL phase for this record
        tenant / graph_id / branch: Graph scope
        base_revision / new_revision: Snapshot parent and staged/published head
        staged_root_cid: Durable CID of staged payload (PREPARE+)
        lease_id / lease_epoch: Graph-scoped fencing token
        idempotency_key: Key for idempotent replay across retries
        record_seq: Monotonic sequence within a transaction
    """

    txn_id: str
    timestamp: float
    operations: List[Operation]
    prev_wal_cid: Optional[str] = None
    txn_state: TransactionState = TransactionState.ACTIVE
    isolation_level: IsolationLevel = IsolationLevel.REPEATABLE_READ
    read_set: List[str] = field(default_factory=list)
    write_set: List[str] = field(default_factory=list)
    phase: Optional[WALPhase] = None
    tenant: Optional[str] = None
    graph_id: Optional[str] = None
    branch: Optional[str] = None
    base_revision: Optional[str] = None
    new_revision: Optional[str] = None
    staged_root_cid: Optional[str] = None
    lease_id: Optional[str] = None
    lease_epoch: Optional[int] = None
    idempotency_key: Optional[str] = None
    record_seq: int = 0

    def resolved_phase(self) -> WALPhase:
        """Resolve durable phase from explicit phase or txn_state."""
        if self.phase is not None:
            return self.phase
        mapped = txn_state_to_phase(self.txn_state)
        if mapped is not None:
            return mapped
        return WALPhase.INTENT

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert WAL entry to dictionary for IPLD storage.

        Returns:
            Dictionary representation suitable for IPLD
        """
        d: Dict[str, Any] = {
            "txn_id": self.txn_id,
            "timestamp": self.timestamp,
            "operations": [op.to_dict() for op in self.operations],
            "prev_wal_cid": self.prev_wal_cid,
            "txn_state": self.txn_state.value,
            "isolation_level": self.isolation_level.value,
            "read_set": self.read_set,
            "write_set": self.write_set,
        }
        if self.phase is not None:
            d["phase"] = self.phase.value
        if self.tenant is not None:
            d["tenant"] = self.tenant
        if self.graph_id is not None:
            d["graph_id"] = self.graph_id
        if self.branch is not None:
            d["branch"] = self.branch
        if self.base_revision is not None:
            d["base_revision"] = self.base_revision
        if self.new_revision is not None:
            d["new_revision"] = self.new_revision
        if self.staged_root_cid is not None:
            d["staged_root_cid"] = self.staged_root_cid
        if self.lease_id is not None:
            d["lease_id"] = self.lease_id
        if self.lease_epoch is not None:
            d["lease_epoch"] = self.lease_epoch
        if self.idempotency_key is not None:
            d["idempotency_key"] = self.idempotency_key
        if self.record_seq:
            d["record_seq"] = self.record_seq
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WALEntry":
        """
        Create WAL entry from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            WALEntry instance
        """
        phase_raw = data.get("phase")
        phase = WALPhase(phase_raw) if phase_raw else None
        lease_epoch = data.get("lease_epoch")
        return cls(
            txn_id=data["txn_id"],
            timestamp=data["timestamp"],
            operations=[Operation.from_dict(op) for op in data.get("operations") or []],
            prev_wal_cid=data.get("prev_wal_cid"),
            txn_state=TransactionState(data.get("txn_state", "ACTIVE")),
            isolation_level=IsolationLevel(
                data.get("isolation_level", "REPEATABLE_READ")
            ),
            read_set=data.get("read_set", []),
            write_set=data.get("write_set", []),
            phase=phase,
            tenant=data.get("tenant"),
            graph_id=data.get("graph_id"),
            branch=data.get("branch"),
            base_revision=data.get("base_revision"),
            new_revision=data.get("new_revision"),
            staged_root_cid=data.get("staged_root_cid"),
            lease_id=data.get("lease_id"),
            lease_epoch=int(lease_epoch) if lease_epoch is not None else None,
            idempotency_key=data.get("idempotency_key"),
            record_seq=int(data.get("record_seq") or 0),
        )


@dataclass
class Transaction:
    """
    Active transaction context.

    Maintains transaction state during execution and tracks
    operations for commit/rollback.

    Attributes:
        txn_id: Unique transaction identifier
        isolation_level: Isolation level for this transaction
        state: Current transaction state
        operations: List of operations performed
        read_set: CIDs of entities read (for conflict detection)
        write_set: IDs of entities written
        start_time: When transaction started
        snapshot_cid: Graph CID at transaction start (for snapshot isolation)
        wal_entries: CIDs of WAL entries created by this transaction
        tenant / graph_id / branch: Graph scope for multi-graph MVCC
        base_revision: Snapshot revision at begin
        staged_revision_id / staged_root_cid: Prepared publication targets
        lease_id / lease_epoch: Writer fencing token
        idempotency_key: Client retry key
        phase: Current durable protocol phase
    """

    txn_id: str
    isolation_level: IsolationLevel
    state: TransactionState = TransactionState.ACTIVE
    operations: List[Operation] = field(default_factory=list)
    read_set: List[str] = field(default_factory=list)
    write_set: List[str] = field(default_factory=list)
    start_time: float = field(default_factory=lambda: datetime.now().timestamp())
    snapshot_cid: Optional[str] = None
    wal_entries: List[str] = field(default_factory=list)
    tenant: Optional[str] = None
    graph_id: Optional[str] = None
    branch: Optional[str] = None
    base_revision: Optional[str] = None
    staged_revision_id: Optional[str] = None
    staged_root_cid: Optional[str] = None
    lease_id: Optional[str] = None
    lease_epoch: Optional[int] = None
    idempotency_key: Optional[str] = None
    phase: WALPhase = WALPhase.INTENT
    record_seq: int = 0

    def add_operation(self, operation: Operation) -> None:
        """
        Add an operation to the transaction.

        Args:
            operation: Operation to add
        """
        if len(self.operations) >= MAX_WAL_OPERATIONS_PER_ENTRY:
            raise WALBoundExceededError(
                f"operation count would exceed bound {MAX_WAL_OPERATIONS_PER_ENTRY}",
                details={
                    "bound": MAX_WAL_OPERATIONS_PER_ENTRY,
                    "current": len(self.operations),
                    "txn_id": self.txn_id,
                },
            )
        self.operations.append(operation)

        # Track write set
        if operation.type in (OperationType.WRITE_NODE, OperationType.DELETE_NODE):
            if operation.node_id and operation.node_id not in self.write_set:
                if len(self.write_set) >= MAX_WRITE_SET_SIZE:
                    raise WALBoundExceededError(
                        f"write_set would exceed bound {MAX_WRITE_SET_SIZE}",
                        details={"bound": MAX_WRITE_SET_SIZE, "txn_id": self.txn_id},
                    )
                self.write_set.append(operation.node_id)
        elif operation.type in (
            OperationType.WRITE_RELATIONSHIP,
            OperationType.DELETE_RELATIONSHIP,
        ):
            if operation.rel_id and operation.rel_id not in self.write_set:
                if len(self.write_set) >= MAX_WRITE_SET_SIZE:
                    raise WALBoundExceededError(
                        f"write_set would exceed bound {MAX_WRITE_SET_SIZE}",
                        details={"bound": MAX_WRITE_SET_SIZE, "txn_id": self.txn_id},
                    )
                self.write_set.append(operation.rel_id)

    def add_read(self, entity_cid: str) -> None:
        """
        Track a read operation for conflict detection.

        Args:
            entity_cid: CID of entity read
        """
        if entity_cid and entity_cid not in self.read_set:
            if len(self.read_set) >= MAX_READ_SET_SIZE:
                raise WALBoundExceededError(
                    f"read_set would exceed bound {MAX_READ_SET_SIZE}",
                    details={"bound": MAX_READ_SET_SIZE, "txn_id": self.txn_id},
                )
            self.read_set.append(entity_cid)

    def is_active(self) -> bool:
        """Check if transaction is in active state."""
        return self.state == TransactionState.ACTIVE

    def can_commit(self) -> bool:
        """Check if transaction can be committed."""
        return self.state in (
            TransactionState.ACTIVE,
            TransactionState.PREPARING,
            TransactionState.PREPARED,
            TransactionState.PUBLISHED,
        )


class ConflictError(Exception):
    """
    Raised when a transaction conflict is detected.

    Indicates write-write conflict where two transactions
    modified the same entity, or optimistic head CAS failed.
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TransactionAbortedError(Exception):
    """Raised when operation attempted on aborted transaction."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DeadlockDetectedError(Exception):
    """
    Raised when a deadlock is detected between transactions.

    Note: Full deadlock detection is a future enhancement.
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LeaseFencedError(Exception):
    """
    Raised when a writer lease epoch is stale (graph-scoped fencing).

    Stale holders must not mutate; acquire a new lease with a higher epoch.
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class WALBoundExceededError(Exception):
    """Raised when a WAL record would exceed configured hard bounds."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class IdempotencyConflictError(Exception):
    """Raised when the same idempotency key is reused with a different request."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


__all__ = [
    "MAX_WAL_OPERATIONS_PER_ENTRY",
    "MAX_WAL_ENTRY_BYTES",
    "MAX_WRITE_SET_SIZE",
    "MAX_READ_SET_SIZE",
    "MAX_STAGED_DELTA_BYTES",
    "MAX_ACTIVE_TRANSACTIONS",
    "IsolationLevel",
    "TransactionState",
    "WALPhase",
    "RecoveryAction",
    "OperationType",
    "Operation",
    "SnapshotRevision",
    "StagedDelta",
    "LeaseFence",
    "HeadCASResult",
    "RecoveryDecision",
    "RECOVERY_ACTION_MATRIX",
    "recovery_action_for_phase",
    "phase_rank",
    "txn_state_to_phase",
    "phase_to_txn_state",
    "WALEntry",
    "Transaction",
    "ConflictError",
    "TransactionAbortedError",
    "DeadlockDetectedError",
    "LeaseFencedError",
    "WALBoundExceededError",
    "IdempotencyConflictError",
]
