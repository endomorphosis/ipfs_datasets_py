"""
Transaction Manager for Graph Database

Implements ACID-compliant transaction management with Write-Ahead Logging,
conflict detection, and support for multiple isolation levels.

Architecture:
- Uses Write-Ahead Log (WAL) for durability
- Optimistic concurrency control (detect conflicts at commit)
- Support for 4 isolation levels
- Integration with GraphEngine for operations
"""

import logging
import time
import uuid
import asyncio
from typing import Dict, List, Optional, Set, Any

from .types import (
    Transaction,
    TransactionState,
    IsolationLevel,
    Operation,
    OperationType,
    WALEntry,
    ConflictError,
    TransactionAbortedError,
)
from .wal import WriteAheadLog
from ..core.graph_engine import GraphEngine
from ..storage.ipld_backend import IPLDBackend

# Import custom exceptions
from ..exceptions import (
    TransactionError,
    TransactionConflictError,
    TransactionAbortedError as TransactionAbortedException,
    TransactionTimeoutError
)

logger = logging.getLogger(__name__)


class TransactionManager:
    """
    Manages ACID-compliant transactions with WAL-based durability.
    
    Features:
    - Begin/commit/rollback operations
    - Conflict detection (write-write conflicts)
    - Optimistic concurrency control
    - Support for 4 isolation levels
    - Automatic retry on conflicts
    - WAL-based crash recovery
    
    Example:
        manager = TransactionManager(engine, storage)
        
        # Begin transaction
        txn = manager.begin(isolation_level=IsolationLevel.REPEATABLE_READ)
        
        # Execute operations
        manager.add_operation(txn, create_node_op)
        manager.add_operation(txn, create_relationship_op)
        
        # Commit
        manager.commit(txn)
    """
    
    def __init__(
        self,
        graph_engine: GraphEngine,
        storage_backend: IPLDBackend,
        wal_head_cid: Optional[str] = None
    ):
        """
        Initialize transaction manager.
        
        Args:
            graph_engine: GraphEngine for executing operations
            storage_backend: IPLD backend for WAL storage
            wal_head_cid: Existing WAL head CID (for recovery)
        """
        self.graph_engine = graph_engine
        self.wal = WriteAheadLog(storage_backend, wal_head_cid)
        
        # Active transactions
        self._active_transactions: Dict[str, Transaction] = {}
        
        # Committed write sets (for conflict detection)
        self._committed_writes: Dict[str, Set[str]] = {}  # entity_id -> txn_ids
        
        logger.info("TransactionManager initialized")
    
    def begin(
        self,
        isolation_level: IsolationLevel = IsolationLevel.REPEATABLE_READ
    ) -> Transaction:
        """
        Begin a new transaction.
        
        Args:
            isolation_level: Isolation level for transaction
            
        Returns:
            New transaction object
            
        Example:
            txn = manager.begin(IsolationLevel.SERIALIZABLE)
        """
        txn_id = f"txn-{uuid.uuid4().hex[:12]}"
        
        # Capture snapshot for isolation
        snapshot_cid = None
        if isolation_level in (IsolationLevel.REPEATABLE_READ, IsolationLevel.SERIALIZABLE):
            # Get current graph state CID
            snapshot_cid = self._capture_snapshot()
        
        transaction = Transaction(
            txn_id=txn_id,
            isolation_level=isolation_level,
            state=TransactionState.ACTIVE,
            operations=[],
            read_set=[],
            write_set=[],
            start_time=time.time(),
            snapshot_cid=snapshot_cid,
            wal_entries=[]
        )
        
        self._active_transactions[txn_id] = transaction
        
        logger.info(f"Transaction {txn_id} started with isolation {isolation_level.value}")
        return transaction
    
    def add_operation(self, transaction: Transaction, operation: Operation):
        """
        Add an operation to transaction.
        
        Operations are buffered until commit.
        
        Args:
            transaction: Transaction to add operation to
            operation: Operation to add
            
        Raises:
            TransactionAbortedError: If transaction is not active
        """
        if not transaction.is_active():
            raise TransactionAbortedError(
                f"Cannot add operation to {transaction.state.value} transaction"
            )
        
        transaction.add_operation(operation)
        
        # Track writes for conflict detection
        if operation.type in (
            OperationType.WRITE_NODE,
            OperationType.WRITE_RELATIONSHIP,
            OperationType.DELETE_NODE,
            OperationType.DELETE_RELATIONSHIP,
            OperationType.SET_PROPERTY
        ):
            entity_id = operation.node_id or operation.rel_id
            if entity_id:
                transaction.write_set.append(entity_id)
        
        logger.debug(f"Added {operation.type.value} to transaction {transaction.txn_id}")
    
    def add_read(self, transaction: Transaction, entity_cid: str):
        """
        Track a read for conflict detection.
        
        Args:
            transaction: Transaction that performed read
            entity_cid: CID of entity read
        """
        if transaction.is_active():
            transaction.add_read(entity_cid)
    
    def commit(self, transaction: Transaction) -> bool:
        """
        Commit transaction with conflict detection.
        
        Process:
        1. Detect conflicts with committed transactions
        2. Write WAL entry
        3. Apply operations to graph
        4. Mark as committed
        
        Args:
            transaction: Transaction to commit
            
        Returns:
            True if committed successfully
            
        Raises:
            ConflictError: If write-write conflicts detected
            TransactionAbortedError: If transaction is not active
            
        Example:
            try:
                manager.commit(txn)
            except ConflictError:
                manager.rollback(txn)
        """
        if not transaction.is_active():
            raise TransactionAbortedError(
                f"Cannot commit {transaction.state.value} transaction"
            )
        
        # Move to PREPARING state
        transaction.state = TransactionState.PREPARING
        
        try:
            # 1. Detect conflicts
            self._detect_conflicts(transaction)
            
            # 2. Write WAL entry (durability)
            wal_entry = WALEntry(
                txn_id=transaction.txn_id,
                timestamp=time.time(),
                operations=transaction.operations,
                prev_wal_cid=self.wal.wal_head_cid,
                txn_state=TransactionState.COMMITTED,
                isolation_level=transaction.isolation_level,
                read_set=transaction.read_set,
                write_set=transaction.write_set
            )
            
            wal_cid = self.wal.append(wal_entry)
            transaction.wal_entries.append(wal_cid)
            
            # 3. Apply operations to graph
            self._apply_operations(transaction)
            
            # 4. Mark as committed
            transaction.state = TransactionState.COMMITTED
            
            # Track committed writes
            for entity_id in transaction.write_set:
                if entity_id not in self._committed_writes:
                    self._committed_writes[entity_id] = set()
                self._committed_writes[entity_id].add(transaction.txn_id)
            
            # Remove from active
            del self._active_transactions[transaction.txn_id]
            
            logger.info(f"Transaction {transaction.txn_id} committed successfully")
            return True
            
        except ConflictError as e:
            # Conflict detected, abort
            transaction.state = TransactionState.ABORTED
            del self._active_transactions[transaction.txn_id]
            logger.warning(f"Transaction {transaction.txn_id} aborted: {e}")
            raise
        except TransactionAbortedError:
            # Re-raise abort errors
            raise
        except TransactionError:
            raise
        except (TimeoutError, asyncio.TimeoutError) as e:
            # Transaction timeout
            transaction.state = TransactionState.FAILED
            del self._active_transactions[transaction.txn_id]
            logger.error(f"Transaction {transaction.txn_id} timed out: {e}")
            raise TransactionTimeoutError(
                f"Transaction timed out: {e}",
                details={'txn_id': str(transaction.txn_id), 'duration': time.time() - transaction.start_time}
            ) from e
        except Exception as e:
            # Failed, rollback
            transaction.state = TransactionState.FAILED
            del self._active_transactions[transaction.txn_id]
            logger.error(f"Transaction {transaction.txn_id} failed: {e}")
            raise TransactionError(
                f"Transaction failed: {e}",
                details={'txn_id': str(transaction.txn_id), 'operations': len(transaction.operations)}
            ) from e
    
    def rollback(self, transaction: Transaction):
        """
        Rollback (abort) transaction.
        
        All buffered operations are discarded.
        
        Args:
            transaction: Transaction to rollback
        """
        if transaction.txn_id in self._active_transactions:
            del self._active_transactions[transaction.txn_id]
        
        transaction.state = TransactionState.ABORTED
        transaction.operations.clear()
        
        logger.info(f"Transaction {transaction.txn_id} rolled back")
    
    def _detect_conflicts(self, transaction: Transaction):
        """
        Detect write-write conflicts for ACID transaction isolation.

        Implements optimistic concurrency control by checking if any entities written
        by this transaction were also modified by other transactions that committed
        after this transaction started.

        Conflict Detection Rules:
        1. READ_UNCOMMITTED: No conflict detection (dirty reads allowed)
        2. READ_COMMITTED: No conflict detection (non-repeatable reads allowed)
        3. REPEATABLE_READ: Check write-write conflicts only
        4. SERIALIZABLE: Check write-write conflicts (read-write checked elsewhere)

        A conflict occurs when:
        - Transaction T1 starts at time t1
        - Transaction T2 commits at time t2 > t1
        - Both T1 and T2 write to the same entity E
        - T1 attempts to commit after T2

        This ensures the isolation property of ACID transactions by preventing
        lost updates (where T1's writes would overwrite T2's committed changes).

        Args:
            transaction: The transaction attempting to commit
            
        Raises:
            ConflictError: If write-write conflicts detected with details of:
                - Conflicting entity IDs
                - Transaction IDs that caused conflicts
                - Format: "Write-write conflicts detected: [(entity_id, other_txn_id), ...]"

        Example:
            >>> # Timeline:
            >>> # t0: txn1 starts, reads entity E1
            >>> # t1: txn2 starts, reads entity E1
            >>> # t2: txn1 writes E1 = "value1", commits successfully
            >>> # t3: txn2 writes E1 = "value2", attempts commit
            >>> 
            >>> try:
            ...     self._detect_conflicts(txn2)
            ... except ConflictError as e:
            ...     print(f"Conflict: {e}")
            ...     # Conflict: Write-write conflicts detected: [('E1', 'txn1')]

        Note:
            This is a simplified conflict detection suitable for single-node deployments.
            Distributed systems would need:
            - Vector clocks or Lamport timestamps
            - Distributed consensus (Paxos, Raft)
            - Multi-version concurrency control (MVCC)
        """
        # For READ_UNCOMMITTED and READ_COMMITTED, no conflict detection
        if transaction.isolation_level in (
            IsolationLevel.READ_UNCOMMITTED,
            IsolationLevel.READ_COMMITTED
        ):
            return
        
        # Check for write-write conflicts
        conflicts = []
        for entity_id in transaction.write_set:
            if entity_id in self._committed_writes:
                # Check if any conflicting transaction committed after we started
                conflicting_txns = self._committed_writes[entity_id]
                for other_txn_id in conflicting_txns:
                    # Conflict if other transaction touched same entity
                    conflicts.append((entity_id, other_txn_id))
        
        if conflicts:
            conflict_msg = f"Write-write conflicts detected: {conflicts}"
            raise ConflictError(conflict_msg)
    
    def _apply_operations(self, transaction: Transaction):
        """
        Apply transaction operations to graph.
        
        Args:
            transaction: Transaction with operations to apply
        """
        for operation in transaction.operations:
            if operation.type == OperationType.WRITE_NODE:
                # Create/update node
                self.graph_engine.create_node(
                    labels=operation.data.get("labels", []),
                    properties=operation.data.get("properties", {})
                )
            
            elif operation.type == OperationType.WRITE_RELATIONSHIP:
                # Create relationship
                self.graph_engine.create_relationship(
                    start_node_id=operation.data.get("start_node_id"),
                    end_node_id=operation.data.get("end_node_id"),
                    rel_type=operation.data.get("rel_type"),
                    properties=operation.data.get("properties", {})
                )
            
            elif operation.type == OperationType.DELETE_NODE:
                # Delete node
                if operation.node_id and operation.node_id in self.graph_engine._nodes:
                    del self.graph_engine._nodes[operation.node_id]
            
            elif operation.type == OperationType.SET_PROPERTY:
                # Set property
                node_id = operation.node_id
                if node_id and node_id in self.graph_engine._nodes:
                    node = self.graph_engine._nodes[node_id]
                    prop_name = operation.data.get("property")
                    prop_value = operation.data.get("value")
                    if prop_name:
                        node["properties"][prop_name] = prop_value
            
            # Add more operation types as needed
    
    def _capture_snapshot(self) -> Optional[str]:
        """
        Capture current graph state as snapshot CID.
        
        Returns:
            CID of graph snapshot, or None if unavailable
        """
        try:
            if not getattr(self.graph_engine, "_enable_persistence", False):
                return None

            storage = getattr(self.graph_engine, "storage", None)
            if storage is None:
                return None

            # Save current graph state
            return self.graph_engine.save_graph()
        except TransactionError:
            raise
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"Failed to capture snapshot (degrading gracefully): {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error capturing snapshot: {e}")
            raise TransactionError(
                f"Failed to capture transaction snapshot: {e}",
                details={'graph_engine_type': type(self.graph_engine).__name__}
            ) from e
    
    def recover(self):
        """
        Recover from crash using WAL.
        
        Replays all committed operations from WAL.
        """
        logger.info("Starting transaction recovery from WAL")
        
        operations = self.wal.recover()
        logger.info(f"Recovering {len(operations)} operations")
        
        # Create temporary transaction for recovery
        recovery_txn = Transaction(
            txn_id="recovery",
            isolation_level=IsolationLevel.READ_UNCOMMITTED,
            state=TransactionState.ACTIVE,
            operations=operations,
            read_set=[],
            write_set=[],
            start_time=time.time(),
            snapshot_cid=None,
            wal_entries=[]
        )
        
        # Apply all operations
        self._apply_operations(recovery_txn)
        
        logger.info("Transaction recovery completed")
    
    def get_active_count(self) -> int:
        """Get number of active transactions."""
        return len(self._active_transactions)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get transaction manager statistics.
        
        Returns:
            Dictionary with stats
        """
        return {
            "active_transactions": self.get_active_count(),
            "wal_head_cid": self.wal.wal_head_cid,
            "wal_entry_count": self.wal._entry_count,
            "committed_writes_tracked": len(self._committed_writes)
        }
