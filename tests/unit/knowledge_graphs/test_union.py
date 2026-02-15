"""
Tests for UNION and UNION ALL (Phase 1, Task 1.2 continued)

This test suite validates UNION functionality:
- Basic UNION (removes duplicates)
- UNION ALL (keeps all results)
- Multiple result sets
- Column alignment

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine


class TestUnion:
    """Test suite for UNION functionality."""
    
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
        
        # Create relationships
        graph_engine.create_relationship("KNOWS", alice.id, bob.id)
        graph_engine.create_relationship("KNOWS", bob.id, charlie.id)
        
        return executor, graph_engine
    
    def test_union_basic(self, query_executor):
        """
        GIVEN: A graph with people
        WHEN: Using UNION to combine two queries
        THEN: Returns combined results without duplicates
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) WHERE n.age < 30 RETURN n.name "
            "UNION "
            "MATCH (n:Person) WHERE n.age > 30 RETURN n.name"
        )
        
        # THEN
        records = list(result)
        # Should have Bob (age 25) and Charlie (age 35)
        assert len(records) >= 2
        names = [rec._values[0] for rec in records]
        assert "Bob" in names
        assert "Charlie" in names
    
    def test_union_all(self, query_executor):
        """
        GIVEN: A graph with people
        WHEN: Using UNION ALL
        THEN: Returns all results including duplicates
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) RETURN n.name "
            "UNION ALL "
            "MATCH (n:Person) RETURN n.name"
        )
        
        # THEN
        records = list(result)
        # Should have 6 results (3 people × 2 queries)
        assert len(records) == 6
    
    def test_union_removes_duplicates(self, query_executor):
        """
        GIVEN: A graph with people
        WHEN: Using UNION on overlapping queries
        THEN: Removes duplicate results
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) WHERE n.age >= 25 RETURN n.name "
            "UNION "
            "MATCH (n:Person) WHERE n.age <= 35 RETURN n.name"
        )
        
        # THEN
        records = list(result)
        # Should have 3 unique people (not 6)
        assert len(records) == 3
        
        # Check no duplicates
        names = [rec._values[0] for rec in records]
        assert len(names) == len(set(names))
    
    def test_union_all_keeps_duplicates(self, query_executor):
        """
        GIVEN: A graph with people
        WHEN: Using UNION ALL on overlapping queries
        THEN: Keeps all results including duplicates
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) WHERE n.age >= 25 RETURN n.name "
            "UNION ALL "
            "MATCH (n:Person) WHERE n.age <= 35 RETURN n.name"
        )
        
        # THEN
        records = list(result)
        # Should have 6 results (all 3 people match both conditions)
        assert len(records) == 6
    
    def test_union_with_different_filters(self, query_executor):
        """
        GIVEN: A graph with people
        WHEN: Using UNION with different WHERE clauses
        THEN: Returns union of both result sets
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) WHERE n.name = 'Alice' RETURN n.name "
            "UNION "
            "MATCH (n:Person) WHERE n.name = 'Bob' RETURN n.name"
        )
        
        # THEN
        records = list(result)
        assert len(records) == 2
        names = [rec._values[0] for rec in records]
        assert "Alice" in names
        assert "Bob" in names
    
    def test_union_empty_results(self, query_executor):
        """
        GIVEN: A graph with people
        WHEN: One part of UNION returns no results
        THEN: Returns results from other part
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) WHERE n.age > 100 RETURN n.name "
            "UNION "
            "MATCH (n:Person) RETURN n.name"
        )
        
        # THEN
        records = list(result)
        # Should have 3 results from second query
        assert len(records) == 3


class TestUnionEdgeCases:
    """Test edge cases for UNION."""
    
    @pytest.fixture
    def query_executor(self):
        """Create QueryExecutor."""
        graph_engine = GraphEngine()
        return QueryExecutor(graph_engine=graph_engine), graph_engine
    
    def test_union_both_empty(self, query_executor):
        """
        GIVEN: An empty graph
        WHEN: Using UNION with both parts empty
        THEN: Returns empty results
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) RETURN n "
            "UNION "
            "MATCH (m:Person) RETURN m"
        )
        
        # THEN
        records = list(result)
        assert len(records) == 0
    
    def test_union_with_aggregations(self, query_executor):
        """
        GIVEN: A graph with data
        WHEN: Using UNION with aggregations
        THEN: Combines aggregated results
        """
        # GIVEN
        executor, engine = query_executor
        engine.create_node(labels=["Person"], properties={"name": "Alice", "type": "A"})
        engine.create_node(labels=["Person"], properties={"name": "Bob", "type": "A"})
        engine.create_node(labels=["Person"], properties={"name": "Charlie", "type": "B"})
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Person) WHERE n.type = 'A' RETURN COUNT(n) AS count "
            "UNION "
            "MATCH (n:Person) WHERE n.type = 'B' RETURN COUNT(n) AS count"
        )
        
        # THEN
        records = list(result)
        # Should have 2 results (one for each type)
        assert len(records) == 2


class TestMultipleUnions:
    """Test multiple UNION operations."""
    
    @pytest.fixture
    def query_executor(self):
        """Create QueryExecutor with data."""
        graph_engine = GraphEngine()
        executor = QueryExecutor(graph_engine=graph_engine)
        
        # Create nodes
        for i in range(1, 6):
            graph_engine.create_node(
                labels=["Number"],
                properties={"value": i}
            )
        
        return executor, graph_engine
    
    def test_three_way_union(self, query_executor):
        """
        GIVEN: A graph with numbered nodes
        WHEN: Using three UNION operations
        THEN: Combines all three result sets
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute(
            "MATCH (n:Number) WHERE n.value = 1 RETURN n.value "
            "UNION "
            "MATCH (n:Number) WHERE n.value = 2 RETURN n.value "
            "UNION "
            "MATCH (n:Number) WHERE n.value = 3 RETURN n.value"
        )
        
        # THEN
        records = list(result)
        assert len(records) == 3
        values = [rec._values[0] for rec in records]
        assert 1 in values
        assert 2 in values
        assert 3 in values


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
