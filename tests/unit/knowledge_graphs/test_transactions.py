"""
Tests for Transaction System

Tests the transaction manager, WAL, and isolation levels.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.transactions import (
    TransactionManager,
    IsolationLevel,
    Operation,
    OperationType,
    ConflictError,
    TransactionAbortedError,
)
from ipfs_datasets_py.knowledge_graphs.core.query_executor import GraphEngine
from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend


class TestTransactionManager:
    """Test Transaction Manager"""
    
    def setup_method(self):
        """Setup for each test"""
        # Create engine and storage (mocked for now)
        self.engine = GraphEngine()
        self.storage = IPLDBackend(cache_capacity=100)
        self.manager = TransactionManager(self.engine, self.storage)
    
    def test_begin_transaction(self):
        """Test: Begin transaction creates valid transaction"""
        # GIVEN a transaction manager
        # WHEN starting a transaction
        txn = self.manager.begin(IsolationLevel.REPEATABLE_READ)
        
        # THEN transaction should be active
        assert txn.is_active()
        assert txn.isolation_level == IsolationLevel.REPEATABLE_READ
        assert len(txn.operations) == 0
    
    def test_add_operation(self):
        """Test: Add operation to transaction"""
        # GIVEN an active transaction
        txn = self.manager.begin()
        
        # WHEN adding an operation
        op = Operation(
            type=OperationType.WRITE_NODE,
            node_id="node-1",
            data={"labels": ["Person"], "properties": {"name": "Alice"}}
        )
        self.manager.add_operation(txn, op)
        
        # THEN operation should be buffered
        assert len(txn.operations) == 1
        assert txn.operations[0].type == OperationType.WRITE_NODE
    
    def test_rollback(self):
        """Test: Rollback aborts transaction"""
        # GIVEN a transaction with operations
        txn = self.manager.begin()
        op = Operation(
            type=OperationType.WRITE_NODE,
            node_id="node-1",
            data={"labels": ["Person"]}
        )
        self.manager.add_operation(txn, op)
        
        # WHEN rolling back
        self.manager.rollback(txn)
        
        # THEN transaction should be aborted
        assert not txn.is_active()
        assert len(txn.operations) == 0
    
    def test_cannot_operate_on_aborted_transaction(self):
        """Test: Cannot add operations to aborted transaction"""
        # GIVEN an aborted transaction
        txn = self.manager.begin()
        self.manager.rollback(txn)
        
        # WHEN trying to add operation
        # THEN should raise error
        with pytest.raises(TransactionAbortedError):
            op = Operation(type=OperationType.WRITE_NODE, node_id="node-1", data={})
            self.manager.add_operation(txn, op)
    
    def test_isolation_levels(self):
        """Test: All isolation levels work"""
        # Test each isolation level
        for level in IsolationLevel:
            txn = self.manager.begin(level)
            assert txn.isolation_level == level
            assert txn.is_active()
            self.manager.rollback(txn)
    
    def test_get_stats(self):
        """Test: Get transaction manager statistics"""
        # GIVEN a manager with active transaction
        txn = self.manager.begin()
        
        # WHEN getting stats
        stats = self.manager.get_stats()
        
        # THEN stats should be valid
        assert "active_transactions" in stats
        assert stats["active_transactions"] == 1
        assert "wal_head_cid" in stats
        
        # Cleanup
        self.manager.rollback(txn)


class TestWALEntry:
    """Test WAL Entry structure"""
    
    def test_wal_entry_creation(self):
        """Test: Create WAL entry"""
        from ipfs_datasets_py.knowledge_graphs.transactions import WALEntry, TransactionState
        
        # WHEN creating entry
        entry = WALEntry(
            txn_id="txn-1",
            timestamp=123.45,
            operations=[],
            prev_wal_cid=None,
            txn_state=TransactionState.COMMITTED,
            isolation_level=IsolationLevel.REPEATABLE_READ,
            read_set=[],
            write_set=[]
        )
        
        # THEN entry should be valid
        assert entry.txn_id == "txn-1"
        assert entry.txn_state == TransactionState.COMMITTED
    
    def test_wal_entry_serialization(self):
        """Test: WAL entry to/from dict"""
        from ipfs_datasets_py.knowledge_graphs.transactions import WALEntry, TransactionState
        
        # GIVEN a WAL entry
        entry = WALEntry(
            txn_id="txn-1",
            timestamp=123.45,
            operations=[],
            prev_wal_cid="bafyrei123",
            txn_state=TransactionState.COMMITTED,
            isolation_level=IsolationLevel.READ_COMMITTED,
            read_set=["cid1"],
            write_set=["entity1"]
        )
        
        # WHEN serializing
        data = entry.to_dict()
        
        # THEN should be dict
        assert isinstance(data, dict)
        assert data["txn_id"] == "txn-1"
        assert data["prev_wal_cid"] == "bafyrei123"
        
        # WHEN deserializing
        restored = WALEntry.from_dict(data)
        
        # THEN should match original
        assert restored.txn_id == entry.txn_id
        assert restored.txn_state == entry.txn_state


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
