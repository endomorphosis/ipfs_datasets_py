"""
Unit tests for Neo4j Driver API

Tests the Neo4j-compatible driver interface including:
- Driver creation and connection
- Session management
- Result and Record handling
- Transaction support
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False

from ipfs_datasets_py.knowledge_graphs.neo4j_compat import (
    GraphDatabase, IPFSDriver, IPFSSession, IPFSTransaction,
    Result, Record, Node, Relationship, Path
)


class TestDriverCreation:
    """Test driver creation and initialization."""
    
    def test_driver_factory(self):
        """Test GraphDatabase.driver() creates IPFSDriver."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        assert driver is not None
        assert isinstance(driver, IPFSDriver)
    
    def test_driver_with_uri_variants(self):
        """Test driver accepts various URI formats."""
        # Standard IPFS URI
        driver1 = GraphDatabase.driver("ipfs://localhost:5001")
        assert driver1 is not None
        
        # Embedded IPFS URI
        driver2 = GraphDatabase.driver("ipfs+embedded://")
        assert driver2 is not None
    
    def test_driver_with_auth(self):
        """Test driver accepts authentication."""
        driver = GraphDatabase.driver(
            "ipfs://localhost:5001",
            auth=("user", "token")
        )
        assert driver is not None
    
    def test_driver_close(self):
        """Test driver can be closed."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        driver.close()
        # Should not raise exception


class TestSessionManagement:
    """Test session creation and management."""
    
    def test_session_creation(self):
        """Test session can be created."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        session = driver.session()
        assert session is not None
        assert isinstance(session, IPFSSession)
        session.close()
        driver.close()
    
    def test_session_context_manager(self):
        """Test session works as context manager."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        with driver.session() as session:
            assert session is not None
        driver.close()
    
    def test_session_close(self):
        """Test session can be closed."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        session = driver.session()
        session.close()
        # Should not raise exception
        driver.close()


class TestResultAndRecord:
    """Test Result and Record functionality."""
    
    def test_result_creation(self):
        """Test Result can be created."""
        records = [
            Record(keys=["name", "age"], values=["Alice", 30]),
            Record(keys=["name", "age"], values=["Bob", 25])
        ]
        result = Result(records)
        assert result is not None
    
    def test_result_iteration(self):
        """Test Result can be iterated."""
        records = [
            Record(keys=["name"], values=["Alice"]),
            Record(keys=["name"], values=["Bob"])
        ]
        result = Result(records)
        
        names = [record["name"] for record in result]
        assert names == ["Alice", "Bob"]
    
    def test_result_single(self):
        """Test Result.single() returns single record."""
        records = [Record(keys=["name"], values=["Alice"])]
        result = Result(records)
        
        record = result.single()
        assert record is not None
        assert record["name"] == "Alice"
    
    def test_result_data(self):
        """Test Result.data() returns list of dicts."""
        records = [
            Record(keys=["name", "age"], values=["Alice", 30]),
            Record(keys=["name", "age"], values=["Bob", 25])
        ]
        result = Result(records)
        
        data = result.data()
        assert len(data) == 2
        assert data[0] == {"name": "Alice", "age": 30}
        assert data[1] == {"name": "Bob", "age": 25}
    
    def test_record_get(self):
        """Test Record can get values by key."""
        record = Record(keys=["name", "age"], values=["Alice", 30])
        assert record.get("name") == "Alice"
        assert record.get("age") == 30
        assert record.get("nonexistent") is None
    
    def test_record_bracket_access(self):
        """Test Record supports bracket notation."""
        record = Record(keys=["name", "age"], values=["Alice", 30])
        assert record["name"] == "Alice"
        assert record["age"] == 30
    
    def test_record_keys(self):
        """Test Record.keys() returns keys."""
        record = Record(keys=["name", "age"], values=["Alice", 30])
        keys = record.keys()
        assert "name" in keys
        assert "age" in keys
    
    def test_record_values(self):
        """Test Record.values() returns values."""
        record = Record(keys=["name", "age"], values=["Alice", 30])
        values = record.values()
        assert "Alice" in values
        assert 30 in values


class TestGraphTypes:
    """Test Node, Relationship, and Path types."""
    
    def test_node_creation(self):
        """Test Node can be created."""
        node = Node(
            node_id="node-123",
            labels=["Person"],
            properties={"name": "Alice", "age": 30}
        )
        assert node is not None
        assert node.id == "node-123"
        assert "Person" in node.labels
        assert node.get("name") == "Alice"
    
    def test_node_labels(self):
        """Test Node.labels property."""
        node = Node(
            node_id="node-123",
            labels=["Person", "Employee"],
            properties={}
        )
        assert len(node.labels) == 2
        assert "Person" in node.labels
        assert "Employee" in node.labels
    
    def test_relationship_creation(self):
        """Test Relationship can be created."""
        rel = Relationship(
            rel_id="rel-123",
            rel_type="KNOWS",
            start_node="node-1",
            end_node="node-2",
            properties={"since": 2020}
        )
        assert rel is not None
        assert rel.id == "rel-123"
        assert rel.type == "KNOWS"
        assert rel.start_node == "node-1"
        assert rel.end_node == "node-2"
        assert rel.get("since") == 2020
    
    def test_path_creation(self):
        """Test Path can be created."""
        node1 = Node("node-1", ["Person"], {"name": "Alice"})
        node2 = Node("node-2", ["Person"], {"name": "Bob"})
        rel = Relationship("rel-1", "KNOWS", "node-1", "node-2", {})
        
        # Path expects nodes in a special format alternating with relationships
        path = Path(node1, rel, node2)
        assert path is not None
        assert len(path.nodes) >= 1


class TestTransactions:
    """Test transaction functionality."""
    
    def test_begin_transaction(self):
        """Test beginning a transaction."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        session = driver.session()
        
        txn = session.begin_transaction()
        assert txn is not None
        assert isinstance(txn, IPFSTransaction)
        
        txn.close()
        session.close()
        driver.close()
    
    def test_transaction_context_manager(self):
        """Test transaction works as context manager."""
        driver = GraphDatabase.driver("ipfs://localhost:5001")
        session = driver.session()
        
        with session.begin_transaction() as txn:
            assert txn is not None
        
        session.close()
        driver.close()


if __name__ == "__main__":
    # Run smoke tests
    print("Running driver creation tests...")
    driver_test = TestDriverCreation()
    driver_test.test_driver_factory()
    driver_test.test_driver_with_uri_variants()
    driver_test.test_driver_with_auth()
    driver_test.test_driver_close()
    print("✅ Driver creation tests passed!")
    
    print("\nRunning session management tests...")
    session_test = TestSessionManagement()
    session_test.test_session_creation()
    session_test.test_session_context_manager()
    session_test.test_session_close()
    print("✅ Session management tests passed!")
    
    print("\nRunning result and record tests...")
    result_test = TestResultAndRecord()
    result_test.test_result_creation()
    result_test.test_result_iteration()
    result_test.test_result_single()
    result_test.test_result_data()
    result_test.test_record_get()
    result_test.test_record_bracket_access()
    result_test.test_record_keys()
    result_test.test_record_values()
    print("✅ Result and Record tests passed!")
    
    print("\nRunning graph types tests...")
    types_test = TestGraphTypes()
    types_test.test_node_creation()
    types_test.test_node_labels()
    types_test.test_relationship_creation()
    types_test.test_path_creation()
    print("✅ Graph types tests passed!")
    
    print("\nRunning transaction tests...")
    txn_test = TestTransactions()
    txn_test.test_begin_transaction()
    txn_test.test_transaction_context_manager()
    print("✅ Transaction tests passed!")
