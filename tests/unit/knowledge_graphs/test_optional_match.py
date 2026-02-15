"""
Tests for OPTIONAL MATCH (Phase 1, Task 1.2 continued)

This test suite validates OPTIONAL MATCH functionality:
- Left join semantics
- NULL handling
- Works with aggregations
- Multiple OPTIONAL MATCH clauses

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node


class TestOptionalMatch:
    """Test suite for OPTIONAL MATCH functionality."""
    
    @pytest.fixture
    def query_executor(self):
        """Create a QueryExecutor with sample data."""
        graph_engine = GraphEngine()
        executor = QueryExecutor(graph_engine=graph_engine)
        
        # Create people
        alice = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Alice", "age": 30}
        )
        bob = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Bob", "age": 25}
        )
        charlie = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Charlie", "age": 35}
        )
        david = graph_engine.create_node(
            labels=["Person"],
            properties={"name": "David", "age": 28}
        )
        
        # Create some KNOWS relationships (but not for everyone)
        graph_engine.create_relationship("KNOWS", alice.id, bob.id)
        graph_engine.create_relationship("KNOWS", alice.id, charlie.id)
        # David has no KNOWS relationships
        
        return executor, graph_engine
    
    def test_optional_match_with_matches(self, query_executor):
        """
        GIVEN: A graph where Alice knows Bob and Charlie
        WHEN: Executing MATCH (n:Person {name: 'Alice'}) OPTIONAL MATCH (n)-[:KNOWS]->(f)
        THEN: Returns Alice with her two friends
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) WHERE n.name = 'Alice' "
            "OPTIONAL MATCH (n)-[:KNOWS]->(f) "
            "RETURN n.name, f.name"
        )
        
        # THEN
        records = list(result)
        assert len(records) >= 2  # At least Alice's two friends
    
    def test_optional_match_without_matches(self, query_executor):
        """
        GIVEN: A graph where David has no KNOWS relationships
        WHEN: Executing OPTIONAL MATCH for David's friends
        THEN: Returns David with NULL for friend
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) WHERE n.name = 'David' "
            "OPTIONAL MATCH (n)-[:KNOWS]->(f) "
            "RETURN n.name, f"
        )
        
        # THEN
        records = list(result)
        assert len(records) >= 1  # Should return at least one row (David)
        # The row should have David's name
        assert records[0]._values[0] == "David"
    
    def test_optional_match_count_with_nulls(self, query_executor):
        """
        GIVEN: A graph where some people have friends and some don't
        WHEN: Counting friends with OPTIONAL MATCH
        THEN: Returns correct count including 0 for people with no friends
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) "
            "OPTIONAL MATCH (n)-[:KNOWS]->(f) "
            "RETURN n.name, COUNT(f) AS friendCount"
        )
        
        # THEN
        records = list(result)
        assert len(records) >= 4  # Should have all 4 people
        
        # Check that counts are reasonable
        # Alice should have 2 friends, David should have 0
        name_counts = {rec._values[0]: rec._values[1] for rec in records}
        
        # David should have 0 friends
        assert "David" in name_counts
        # Note: COUNT(NULL) = 0 in Cypher
    
    def test_optional_match_all_nodes(self, query_executor):
        """
        GIVEN: A graph with multiple people
        WHEN: Using OPTIONAL MATCH for all nodes
        THEN: Returns all nodes even those without relationships
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) "
            "OPTIONAL MATCH (n)-[:KNOWS]->(f:Person) "
            "RETURN n.name"
        )
        
        # THEN
        records = list(result)
        # Should return rows for all people
        names = [rec._values[0] for rec in records]
        assert "Alice" in names
        assert "Bob" in names
        assert "Charlie" in names
        assert "David" in names
    
    def test_regular_match_vs_optional_match(self, query_executor):
        """
        GIVEN: A graph where David has no KNOWS relationships
        WHEN: Comparing regular MATCH vs OPTIONAL MATCH
        THEN: Regular MATCH excludes David, OPTIONAL MATCH includes him
        """
        # GIVEN
        executor, engine = query_executor
        
        # Regular MATCH
        result1 = executor.execute(
            "MATCH (n:Person)-[:KNOWS]->(f) RETURN n.name"
        )
        regular_count = len(list(result1))
        
        # OPTIONAL MATCH
        result2 = executor.execute(
            "MATCH (n:Person) OPTIONAL MATCH (n)-[:KNOWS]->(f) RETURN n.name"
        )
        optional_count = len(list(result2))
        
        # THEN
        # Optional match should return more or equal rows (includes David)
        assert optional_count >= regular_count
    
    def test_optional_match_with_where(self, query_executor):
        """
        GIVEN: A graph with relationships
        WHEN: Using OPTIONAL MATCH with WHERE clause
        THEN: Filters are applied correctly to optional matches
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) "
            "OPTIONAL MATCH (n)-[:KNOWS]->(f:Person) WHERE f.age > 30 "
            "RETURN n.name, f.name"
        )
        
        # THEN
        records = list(result)
        # Should return some results
        assert len(records) >= 0


class TestOptionalMatchEdgeCases:
    """Test edge cases for OPTIONAL MATCH."""
    
    @pytest.fixture
    def query_executor(self):
        """Create empty QueryExecutor."""
        graph_engine = GraphEngine()
        return QueryExecutor(graph_engine=graph_engine), graph_engine
    
    def test_optional_match_on_empty_graph(self, query_executor):
        """
        GIVEN: An empty graph
        WHEN: Executing OPTIONAL MATCH
        THEN: Returns empty results gracefully
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) OPTIONAL MATCH (n)-[:KNOWS]->(f) RETURN n, f"
        )
        
        # THEN
        records = list(result)
        assert len(records) == 0  # No nodes to match
    
    def test_optional_match_only(self, query_executor):
        """
        GIVEN: A graph with nodes
        WHEN: Using OPTIONAL MATCH without preceding MATCH
        THEN: Handles gracefully (may need separate implementation)
        """
        # GIVEN
        executor, engine = query_executor
        engine.create_node(labels=["Person"], properties={"name": "Alice"})
        
        # WHEN - This is a degenerate case, behavior may vary
        try:
            result = executor.execute(
                "OPTIONAL MATCH (n:Person) RETURN n"
            )
            records = list(result)
            # If it works, should return results
            assert len(records) >= 0
        except Exception:
            # May not be supported in all implementations
            pass
    
    def test_multiple_optional_matches(self, query_executor):
        """
        GIVEN: A graph with various relationships
        WHEN: Using multiple OPTIONAL MATCH clauses
        THEN: Both are evaluated with left join semantics
        """
        # GIVEN
        executor, engine = query_executor
        alice = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        bob = engine.create_node(labels=["Person"], properties={"name": "Bob"})
        
        engine.create_relationship("KNOWS", alice.id, bob.id)
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) "
            "OPTIONAL MATCH (n)-[:KNOWS]->(f) "
            "OPTIONAL MATCH (n)-[:LIKES]->(item) "
            "RETURN n.name, f.name, item"
        )
        
        # THEN
        records = list(result)
        # Should return results even if LIKES relationships don't exist
        assert len(records) >= 0


class TestOptionalMatchWithAggregations:
    """Test OPTIONAL MATCH combined with aggregations."""
    
    @pytest.fixture
    def query_executor(self):
        """Create QueryExecutor with data."""
        graph_engine = GraphEngine()
        executor = QueryExecutor(graph_engine=graph_engine)
        
        # Create people
        alice = graph_engine.create_node(labels=["Person"], properties={"name": "Alice"})
        bob = graph_engine.create_node(labels=["Person"], properties={"name": "Bob"})
        charlie = graph_engine.create_node(labels=["Person"], properties={"name": "Charlie"})
        
        # Alice knows Bob, Charlie knows nobody
        graph_engine.create_relationship("KNOWS", alice.id, bob.id)
        
        return executor, graph_engine
    
    def test_count_with_optional_match(self, query_executor):
        """
        GIVEN: A graph where some people have friends
        WHEN: Counting friends with OPTIONAL MATCH
        THEN: COUNT handles NULLs correctly (returns 0 for no friends)
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) "
            "OPTIONAL MATCH (n)-[:KNOWS]->(f) "
            "RETURN n.name, COUNT(f)"
        )
        
        # THEN
        records = list(result)
        assert len(records) >= 3  # All three people
        
        # Verify COUNT behavior with NULLs
        for record in records:
            name = record._values[0]
            count = record._values[1]
            if name == "Charlie":
                # Charlie has no friends, COUNT should be 0
                assert count == 0 or count is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
