"""
Transaction Management Module

This module provides ACID transaction support for the IPFS graph database,
enabling reliable multi-operation workflows with rollback capability.

Architecture (KGP-007 durable MVCC / WAL):
- Write-Ahead Logging (WAL) with INTENT → PREPARE → PUBLISH → COMPLETE phases
- Snapshot revisions for stable readers
- Staged deltas invisible until head publication
- Optimistic branch-head compare-and-swap (CAS)
- Graph-scoped writer lease fencing
- Idempotent phase replay and deterministic crash recovery
- Hard bounds on WAL records and staged deltas

Components:
- TransactionManager: Coordinates transaction lifecycle (legacy GraphEngine path)
- DurableMVCC: Multi-phase durable MVCC coordinator
- WriteAheadLog: Persists multi-phase operations with recovery matrix
- IsolationLevel: Defines transaction isolation semantics

Usage (DurableMVCC)::

    from ipfs_datasets_py.knowledge_graphs.transactions import (
        DurableMVCC, WriteAheadLog, IsolationLevel
    )

    wal = WriteAheadLog(storage)
    mvcc = DurableMVCC(wal)
    txn = mvcc.begin("tenant", "graph", branch="main")
    mvcc.stage_mutations(txn, entities=[{"id": "e1", "type": "Person"}])
    mvcc.prepare(txn)
    mvcc.publish(txn)
    mvcc.complete(txn)

Usage (legacy TransactionManager)::

    from ipfs_datasets_py.knowledge_graphs.transactions import (
        TransactionManager, IsolationLevel
    )
    txn_manager = TransactionManager(storage_backend)
    txn = txn_manager.begin(isolation_level=IsolationLevel.REPEATABLE_READ)
"""

from .types import (
    IsolationLevel,
    TransactionState,
    WALPhase,
    RecoveryAction,
    OperationType,
    Operation,
    WALEntry,
    Transaction,
    SnapshotRevision,
    StagedDelta,
    LeaseFence,
    HeadCASResult,
    RecoveryDecision,
    RECOVERY_ACTION_MATRIX,
    recovery_action_for_phase,
    phase_rank,
    txn_state_to_phase,
    phase_to_txn_state,
    ConflictError,
    TransactionAbortedError,
    DeadlockDetectedError,
    LeaseFencedError,
    WALBoundExceededError,
    IdempotencyConflictError,
    MAX_WAL_OPERATIONS_PER_ENTRY,
    MAX_WAL_ENTRY_BYTES,
    MAX_WRITE_SET_SIZE,
    MAX_READ_SET_SIZE,
    MAX_STAGED_DELTA_BYTES,
    MAX_ACTIVE_TRANSACTIONS,
)
from .wal import WriteAheadLog
from .manager import TransactionManager
from .mvcc import DurableMVCC, InMemoryBranchStore

__all__ = [
    # Types
    "IsolationLevel",
    "TransactionState",
    "WALPhase",
    "RecoveryAction",
    "OperationType",
    "Operation",
    "WALEntry",
    "Transaction",
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
    # Bounds
    "MAX_WAL_OPERATIONS_PER_ENTRY",
    "MAX_WAL_ENTRY_BYTES",
    "MAX_WRITE_SET_SIZE",
    "MAX_READ_SET_SIZE",
    "MAX_STAGED_DELTA_BYTES",
    "MAX_ACTIVE_TRANSACTIONS",
    # WAL / MVCC
    "WriteAheadLog",
    "DurableMVCC",
    "InMemoryBranchStore",
    # Manager
    "TransactionManager",
    # Exceptions
    "ConflictError",
    "TransactionAbortedError",
    "DeadlockDetectedError",
    "LeaseFencedError",
    "WALBoundExceededError",
    "IdempotencyConflictError",
]

__version__ = "0.3.0"
__status__ = "production"  # KGP-007 durable MVCC/WAL
