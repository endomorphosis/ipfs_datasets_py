"""
Transaction Management Module

This module provides ACID transaction support for the IPFS graph database,
enabling reliable multi-operation workflows with rollback capability.

Architecture:
- Write-Ahead Logging (WAL) stored on IPLD
- Optimistic Concurrency Control (OCC) with CID versioning
- Four isolation levels (READ_UNCOMMITTED, READ_COMMITTED, REPEATABLE_READ, SERIALIZABLE)
- Automatic conflict detection and retry

Components:
- TransactionManager: Coordinates transaction lifecycle
- WriteAheadLog: Persists operations before applying
- IsolationLevel: Defines transaction isolation semantics
- ConflictResolver: Handles write-write conflicts

Isolation Levels:
- READ_UNCOMMITTED: No isolation (fastest, not recommended)
- READ_COMMITTED: See only committed changes
- REPEATABLE_READ: Snapshot isolation (default)
- SERIALIZABLE: Full serializability (slowest)

Usage:
    from ipfs_datasets_py.knowledge_graphs.transactions import (
        TransactionManager, IsolationLevel
    )
    
    # Create transaction manager
    txn_manager = TransactionManager(storage_backend)
    
    # Begin transaction
    txn = txn_manager.begin(isolation_level=IsolationLevel.REPEATABLE_READ)
    
    try:
        # Perform operations
        txn.write_node(node_data)
        txn.write_relationship(rel_data)
        
        # Commit changes
        root_cid = txn_manager.commit(txn)
        print(f"Transaction committed: {root_cid}")
    except ConflictError:
        # Rollback on conflict
        txn_manager.rollback(txn)
        raise

Phase 3 Implementation Status:
- Task 3.1: WAL structure design (COMPLETE)
- Task 3.2: WAL implementation (COMPLETE)
- Task 3.3: Transaction Manager (IN PROGRESS)
- Task 3.4-3.6: Integration and testing (PLANNED)

WAL Entry Format:
    {
        "txn_id": "uuid-string",
        "timestamp": 1234567890,
        "operations": [
            {"type": "write_node", "node": {...}},
            {"type": "write_relationship", "rel": {...}},
            {"type": "delete_node", "node_id": "..."}
        ],
        "prev_wal_cid": "bafy..."  # Linked list for recovery
    }

Roadmap:
- Phase 3 (Weeks 5-6): Full implementation with WAL and isolation levels
"""

# Phase 3 implementation (Weeks 5-6)
from .types import (
    IsolationLevel,
    TransactionState,
    OperationType,
    Operation,
    WALEntry,
    Transaction,
    ConflictError,
    TransactionAbortedError,
    DeadlockDetectedError
)
from .wal import WriteAheadLog
from .manager import TransactionManager

__all__ = [
    # Types
    "IsolationLevel",
    "TransactionState",
    "OperationType",
    "Operation",
    "WALEntry",
    "Transaction",
    # WAL
    "WriteAheadLog",
    # Manager
    "TransactionManager",
    # Exceptions
    "ConflictError",
    "TransactionAbortedError",
    "DeadlockDetectedError",
]

# Version info
__version__ = "0.2.0"
__status__ = "development"  # Phase 3 in progress
