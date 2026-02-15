"""
Transaction Type Definitions

Defines data structures for the transaction system including WAL entries,
transaction states, isolation levels, and operation types.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime


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
    Transaction lifecycle states.
    
    Attributes:
        ACTIVE: Transaction is active and accepting operations
        PREPARING: Transaction is preparing to commit
        COMMITTED: Transaction successfully committed
        ABORTED: Transaction was aborted/rolled back
        FAILED: Transaction failed due to error
    """
    ACTIVE = "ACTIVE"
    PREPARING = "PREPARING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


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
            "prev_cid": self.prev_cid
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Operation':
        """Create operation from dictionary."""
        return cls(
            type=OperationType(data["type"]),
            node_id=data.get("node_id"),
            rel_id=data.get("rel_id"),
            data=data.get("data"),
            prev_cid=data.get("prev_cid")
        )


@dataclass
class WALEntry:
    """
    Write-Ahead Log entry stored on IPLD.
    
    Each transaction creates a chain of WAL entries linked by CIDs.
    WAL entries are immutable and form an append-only log.
    
    Attributes:
        txn_id: Unique transaction identifier
        timestamp: Unix timestamp when entry was created
        operations: List of operations in this entry
        prev_wal_cid: CID of previous WAL entry (forms chain)
        txn_state: Current state of the transaction
        isolation_level: Isolation level for this transaction
        read_set: Set of CIDs read by transaction (for conflict detection)
        write_set: Set of entity IDs written by transaction
    """
    txn_id: str
    timestamp: float
    operations: List[Operation]
    prev_wal_cid: Optional[str] = None
    txn_state: TransactionState = TransactionState.ACTIVE
    isolation_level: IsolationLevel = IsolationLevel.REPEATABLE_READ
    read_set: List[str] = field(default_factory=list)
    write_set: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert WAL entry to dictionary for IPLD storage.
        
        Returns:
            Dictionary representation suitable for IPLD
        """
        return {
            "txn_id": self.txn_id,
            "timestamp": self.timestamp,
            "operations": [op.to_dict() for op in self.operations],
            "prev_wal_cid": self.prev_wal_cid,
            "txn_state": self.txn_state.value,
            "isolation_level": self.isolation_level.value,
            "read_set": self.read_set,
            "write_set": self.write_set
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WALEntry':
        """
        Create WAL entry from dictionary.
        
        Args:
            data: Dictionary representation
            
        Returns:
            WALEntry instance
        """
        return cls(
            txn_id=data["txn_id"],
            timestamp=data["timestamp"],
            operations=[Operation.from_dict(op) for op in data["operations"]],
            prev_wal_cid=data.get("prev_wal_cid"),
            txn_state=TransactionState(data.get("txn_state", "ACTIVE")),
            isolation_level=IsolationLevel(data.get("isolation_level", "REPEATABLE_READ")),
            read_set=data.get("read_set", []),
            write_set=data.get("write_set", [])
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
    
    def add_operation(self, operation: Operation) -> None:
        """
        Add an operation to the transaction.
        
        Args:
            operation: Operation to add
        """
        self.operations.append(operation)
        
        # Track write set
        if operation.type in (OperationType.WRITE_NODE, OperationType.DELETE_NODE):
            if operation.node_id and operation.node_id not in self.write_set:
                self.write_set.append(operation.node_id)
        elif operation.type in (OperationType.WRITE_RELATIONSHIP, OperationType.DELETE_RELATIONSHIP):
            if operation.rel_id and operation.rel_id not in self.write_set:
                self.write_set.append(operation.rel_id)
    
    def add_read(self, entity_cid: str) -> None:
        """
        Track a read operation for conflict detection.
        
        Args:
            entity_cid: CID of entity read
        """
        if entity_cid and entity_cid not in self.read_set:
            self.read_set.append(entity_cid)
    
    def is_active(self) -> bool:
        """Check if transaction is in active state."""
        return self.state == TransactionState.ACTIVE
    
    def can_commit(self) -> bool:
        """Check if transaction can be committed."""
        return self.state in (TransactionState.ACTIVE, TransactionState.PREPARING)


class ConflictError(Exception):
    """
    Raised when a transaction conflict is detected.
    
    Indicates write-write conflict where two transactions
    modified the same entity.
    """
    pass


class TransactionAbortedError(Exception):
    """
    Raised when operation attempted on aborted transaction.
    """
    pass


class DeadlockDetectedError(Exception):
    """
    Raised when a deadlock is detected between transactions.
    
    Note: Full deadlock detection is a future enhancement.
    """
    pass
