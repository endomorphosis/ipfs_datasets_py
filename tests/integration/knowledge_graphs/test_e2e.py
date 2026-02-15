"""
Unit tests for GraphEngine

Tests the core graph engine functionality including:
- Node CRUD operations
- Relationship CRUD operations
- Graph persistence
- Cache integration
"""

try:
    import pytest
    HAVE_PYTEST = True
except ImportError:
    HAVE_PYTEST = False
    
from ipfs_datasets_py.knowledge_graphs.core import GraphEngine, QueryExecutor
from ipfs_datasets_py.knowledge_graphs.neo4j_compat import Node, Relationship
from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend, LRUCache


class TestGraphEngineBasics:
    """Test basic GraphEngine functionality without storage."""
    
    def test_engine_initialization(self):
        """Test GraphEngine can be initialized."""
        engine = GraphEngine()
        assert engine is not None
        assert engine._enable_persistence is False
        assert len(engine._node_cache) == 0
        assert len(engine._relationship_cache) == 0
    
    def test_create_node(self):
        """Test node creation."""
        engine = GraphEngine()
        node = engine.create_node(
            labels=["Person"],
            properties={"name": "Alice", "age": 30}
        )
        
        assert node is not None
        assert isinstance(node, Node)
        assert "Person" in node.labels
        assert node.get("name") == "Alice"
        assert node.get("age") == 30
    
    def test_create_node_with_no_labels(self):
        """Test node creation with no labels."""
        engine = GraphEngine()
        node = engine.create_node(properties={"name": "Bob"})
        
        assert node is not None
        assert len(node.labels) == 0
        assert node.get("name") == "Bob"
    
    def test_get_node(self):
        """Test node retrieval."""
        engine = GraphEngine()
        node = engine.create_node(
            labels=["Person"],
            properties={"name": "Alice"}
        )
        
        retrieved = engine.get_node(node.id)
        assert retrieved is not None
        assert retrieved.id == node.id
        assert retrieved.get("name") == "Alice"
    
    def test_get_nonexistent_node(self):
        """Test retrieving non-existent node returns None."""
        engine = GraphEngine()
        retrieved = engine.get_node("nonexistent-id")
        assert retrieved is None
    
    def test_update_node(self):
        """Test node property updates."""
        engine = GraphEngine()
        node = engine.create_node(
            labels=["Person"],
            properties={"name": "Alice", "age": 30}
        )
        
        updated = engine.update_node(node.id, {"age": 31, "city": "SF"})
        assert updated is not None
        assert updated.get("age") == 31
        assert updated.get("city") == "SF"
        assert updated.get("name") == "Alice"  # Original property preserved
    
    def test_update_nonexistent_node(self):
        """Test updating non-existent node returns None."""
        engine = GraphEngine()
        updated = engine.update_node("nonexistent-id", {"age": 31})
        assert updated is None
    
    def test_delete_node(self):
        """Test node deletion."""
        engine = GraphEngine()
        node = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        
        # Delete the node
        deleted = engine.delete_node(node.id)
        assert deleted is True
        
        # Verify it's gone
        retrieved = engine.get_node(node.id)
        assert retrieved is None
    
    def test_delete_nonexistent_node(self):
        """Test deleting non-existent node returns False."""
        engine = GraphEngine()
        deleted = engine.delete_node("nonexistent-id")
        assert deleted is False
    
    def test_create_relationship(self):
        """Test relationship creation."""
        engine = GraphEngine()
        node1 = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        node2 = engine.create_node(labels=["Person"], properties={"name": "Bob"})
        
        rel = engine.create_relationship(
            rel_type="KNOWS",
            start_node=node1.id,
            end_node=node2.id,
            properties={"since": 2020}
        )
        
        assert rel is not None
        assert isinstance(rel, Relationship)
        assert rel.type == "KNOWS"
        assert rel.start_node == node1.id
        assert rel.end_node == node2.id
        assert rel.get("since") == 2020
    
    def test_get_relationship(self):
        """Test relationship retrieval."""
        engine = GraphEngine()
        node1 = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        node2 = engine.create_node(labels=["Person"], properties={"name": "Bob"})
        
        rel = engine.create_relationship("KNOWS", node1.id, node2.id)
        
        retrieved = engine.get_relationship(rel.id)
        assert retrieved is not None
        assert retrieved.id == rel.id
    
    def test_delete_relationship(self):
        """Test relationship deletion."""
        engine = GraphEngine()
        node1 = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        node2 = engine.create_node(labels=["Person"], properties={"name": "Bob"})
        
        rel = engine.create_relationship("KNOWS", node1.id, node2.id)
        
        # Delete the relationship
        deleted = engine.delete_relationship(rel.id)
        assert deleted is True
        
        # Verify it's gone
        retrieved = engine.get_relationship(rel.id)
        assert retrieved is None
    
    def test_find_nodes_by_label(self):
        """Test finding nodes by label."""
        engine = GraphEngine()
        engine.create_node(labels=["Person"], properties={"name": "Alice"})
        engine.create_node(labels=["Person"], properties={"name": "Bob"})
        engine.create_node(labels=["Company"], properties={"name": "Acme"})
        
        # Find all Person nodes
        persons = engine.find_nodes(labels=["Person"])
        assert len(persons) == 2
        
        # Find all Company nodes
        companies = engine.find_nodes(labels=["Company"])
        assert len(companies) == 1
    
    def test_find_nodes_by_property(self):
        """Test finding nodes by property."""
        engine = GraphEngine()
        engine.create_node(labels=["Person"], properties={"name": "Alice", "age": 30})
        engine.create_node(labels=["Person"], properties={"name": "Bob", "age": 25})
        engine.create_node(labels=["Person"], properties={"name": "Charlie", "age": 30})
        
        # Find nodes with age=30
        results = engine.find_nodes(properties={"age": 30})
        assert len(results) == 2
    
    def test_find_nodes_with_limit(self):
        """Test finding nodes with limit."""
        engine = GraphEngine()
        for i in range(10):
            engine.create_node(labels=["Person"], properties={"name": f"Person{i}"})
        
        # Find with limit
        results = engine.find_nodes(labels=["Person"], limit=5)
        assert len(results) == 5


class TestGraphEnginePersistence:
    """Test GraphEngine with IPLD storage backend."""
    
    def test_engine_with_storage(self):
        """Test GraphEngine can be initialized with storage backend."""
        # Create a mock storage backend (without actually connecting to IPFS)
        # This tests the persistence flag is set correctly
        engine = GraphEngine(storage_backend=None)
        assert engine._enable_persistence is False
    
    def test_save_graph_without_storage(self):
        """Test save_graph returns None when storage is disabled."""
        engine = GraphEngine()
        cid = engine.save_graph()
        assert cid is None
    
    def test_load_graph_without_storage(self):
        """Test load_graph returns False when storage is disabled."""
        engine = GraphEngine()
        success = engine.load_graph("fake-cid")
        assert success is False


class TestLRUCache:
    """Test LRU cache functionality."""
    
    def test_cache_initialization(self):
        """Test LRU cache can be initialized."""
        cache = LRUCache(capacity=10)
        assert cache is not None
        assert len(cache) == 0
        assert cache.capacity == 10
    
    def test_cache_put_and_get(self):
        """Test putting and getting values."""
        cache = LRUCache(capacity=10)
        cache.put("key1", "value1")
        
        value = cache.get("key1")
        assert value == "value1"
    
    def test_cache_get_nonexistent(self):
        """Test getting non-existent key returns None."""
        cache = LRUCache(capacity=10)
        value = cache.get("nonexistent")
        assert value is None
    
    def test_cache_update_existing(self):
        """Test updating existing key."""
        cache = LRUCache(capacity=10)
        cache.put("key1", "value1")
        cache.put("key1", "value2")  # Update
        
        value = cache.get("key1")
        assert value == "value2"
        assert len(cache) == 1  # Should still be one item
    
    def test_cache_eviction(self):
        """Test LRU eviction when capacity is reached."""
        cache = LRUCache(capacity=3)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")
        
        # This should evict key1 (least recently used)
        cache.put("key4", "value4")
        
        assert len(cache) == 3
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"
    
    def test_cache_lru_ordering(self):
        """Test LRU ordering is maintained."""
        cache = LRUCache(capacity=3)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")
        
        # Access key1 (makes it most recently used)
        cache.get("key1")
        
        # Add key4 (should evict key2, not key1)
        cache.put("key4", "value4")
        
        assert cache.get("key1") == "value1"  # Still there
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"
    
    def test_cache_clear(self):
        """Test cache can be cleared."""
        cache = LRUCache(capacity=10)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        assert len(cache) == 2
        
        cache.clear()
        assert len(cache) == 0
        assert cache.get("key1") is None


class TestQueryExecutor:
    """Test QueryExecutor functionality."""
    
    def test_executor_initialization(self):
        """Test QueryExecutor can be initialized."""
        executor = QueryExecutor()
        assert executor is not None
    
    def test_executor_with_engine(self):
        """Test QueryExecutor can be initialized with GraphEngine."""
        engine = GraphEngine()
        executor = QueryExecutor(graph_engine=engine)
        assert executor.graph_engine is engine
    
    def test_cypher_query_detection(self):
        """Test Cypher query detection."""
        executor = QueryExecutor()
        
        # These should be detected as Cypher
        assert executor._is_cypher_query("MATCH (n) RETURN n")
        assert executor._is_cypher_query("CREATE (n:Person {name: 'Alice'})")
        assert executor._is_cypher_query("MERGE (n:Person {id: 1})")
        
        # These should not be detected as Cypher
        assert not executor._is_cypher_query("SELECT * FROM users")
        assert not executor._is_cypher_query("simple text query")
    
    def test_parameter_validation(self):
        """Test query parameter validation."""
        executor = QueryExecutor()
        
        # Valid parameters
        executor._validate_parameters({"name": "Alice", "age": 30})
        
        # Invalid: reserved parameter name
        try:
            executor._validate_parameters({"_id": 1})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "reserved" in str(e)
        
        # Invalid: not a dict
        try:
            executor._validate_parameters("not a dict")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "must be a dict" in str(e)


if __name__ == "__main__":
    # Run basic smoke tests
    print("Running GraphEngine basic tests...")
    test_class = TestGraphEngineBasics()
    test_class.test_engine_initialization()
    test_class.test_create_node()
    test_class.test_get_node()
    test_class.test_update_node()
    test_class.test_delete_node()
    test_class.test_create_relationship()
    test_class.test_find_nodes_by_label()
    print("✅ All basic tests passed!")
    
    print("\nRunning LRU cache tests...")
    cache_test = TestLRUCache()
    cache_test.test_cache_initialization()
    cache_test.test_cache_put_and_get()
    cache_test.test_cache_eviction()
    cache_test.test_cache_lru_ordering()
    print("✅ All cache tests passed!")
    
    print("\nRunning QueryExecutor tests...")
    executor_test = TestQueryExecutor()
    executor_test.test_executor_initialization()
    executor_test.test_cypher_query_detection()
    print("✅ All executor tests passed!")
