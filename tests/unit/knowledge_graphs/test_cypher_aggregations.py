"""
Tests for Cypher Aggregation Functions (Phase 1, Task 1.2)

This test suite validates aggregation functions:
- COUNT, SUM, AVG, MIN, MAX, COLLECT
- GROUP BY functionality
- DISTINCT in aggregations

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine
from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node


class TestCypherAggregations:
    """Test suite for Cypher aggregation functions."""
    
    @pytest.fixture
    def query_executor(self):
        """Create a QueryExecutor with GraphEngine and sample data."""
        graph_engine = GraphEngine()
        executor = QueryExecutor(graph_engine=graph_engine)
        
        # Create sample data: People with different ages in different cities
        graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Alice", "age": 30, "city": "NYC"}
        )
        graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Bob", "age": 25, "city": "NYC"}
        )
        graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Charlie", "age": 35, "city": "LA"}
        )
        graph_engine.create_node(
            labels=["Person"],
            properties={"name": "David", "age": 28, "city": "LA"}
        )
        graph_engine.create_node(
            labels=["Person"],
            properties={"name": "Eve", "age": 32, "city": "LA"}
        )
        
        return executor, graph_engine
    
    def test_count_all(self, query_executor):
        """
        GIVEN: A graph with 5 Person nodes
        WHEN: Executing MATCH (n:Person) RETURN COUNT(n)
        THEN: Returns count of 5
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN COUNT(n)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        # The count should be accessible in the record
        assert records[0][0] == 5 or records[0].get("COUNT(n)") == 5
    
    def test_count_star(self, query_executor):
        """
        GIVEN: A graph with 5 Person nodes
        WHEN: Executing MATCH (n:Person) RETURN COUNT(*)
        THEN: Returns count of 5
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN COUNT(*)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        # Should return 5
        count_value = records[0][0] if len(records[0]._values) > 0 else 0
        assert count_value == 5
    
    def test_sum_ages(self, query_executor):
        """
        GIVEN: A graph with people of ages 30, 25, 35, 28, 32
        WHEN: Executing MATCH (n:Person) RETURN SUM(n.age)
        THEN: Returns sum of 150
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN SUM(n.age)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        sum_value = records[0][0]
        assert sum_value == 150  # 30 + 25 + 35 + 28 + 32
    
    def test_avg_age(self, query_executor):
        """
        GIVEN: A graph with people of various ages
        WHEN: Executing MATCH (n:Person) RETURN AVG(n.age)
        THEN: Returns average age of 30
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN AVG(n.age)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        avg_value = records[0][0]
        assert avg_value == 30.0  # (30 + 25 + 35 + 28 + 32) / 5
    
    def test_min_max_age(self, query_executor):
        """
        GIVEN: A graph with people of various ages
        WHEN: Executing MATCH (n:Person) RETURN MIN(n.age), MAX(n.age)
        THEN: Returns minimum 25 and maximum 35
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN MIN(n.age), MAX(n.age)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        record = records[0]
        # Check both values are present
        assert 25 in record._values  # MIN
        assert 35 in record._values  # MAX
    
    def test_collect_names(self, query_executor):
        """
        GIVEN: A graph with people
        WHEN: Executing MATCH (n:Person) RETURN COLLECT(n.name)
        THEN: Returns list of all names
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN COLLECT(n.name)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        collected = records[0][0]
        assert isinstance(collected, list)
        assert len(collected) == 5
        assert "Alice" in collected
        assert "Bob" in collected
    
    def test_group_by_city_count(self, query_executor):
        """
        GIVEN: A graph with people in different cities (2 in NYC, 3 in LA)
        WHEN: Executing MATCH (n:Person) RETURN n.city, COUNT(n) GROUP BY n.city
        THEN: Returns counts per city
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN - Note: Cypher syntax actually doesn't need explicit GROUP BY
        result = executor.execute("MATCH (n:Person) RETURN n.city, COUNT(n)")
        
        # THEN
        records = list(result)
        assert len(records) == 2  # Two groups: NYC and LA
        
        # Check that we have results for both cities
        cities = [rec._values[0] for rec in records]
        counts = [rec._values[1] for rec in records]
        
        assert "NYC" in cities
        assert "LA" in cities
        
        # NYC should have 2, LA should have 3
        nyc_idx = cities.index("NYC")
        la_idx = cities.index("LA")
        assert counts[nyc_idx] == 2
        assert counts[la_idx] == 3
    
    def test_group_by_with_avg(self, query_executor):
        """
        GIVEN: A graph with people in different cities
        WHEN: Executing MATCH (n:Person) RETURN n.city, AVG(n.age)
        THEN: Returns average age per city
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN n.city, AVG(n.age)")
        
        # THEN
        records = list(result)
        assert len(records) == 2  # Two cities
        
        # Verify both cities present and averages are reasonable
        for record in records:
            city = record._values[0]
            avg_age = record._values[1]
            
            if city == "NYC":
                # Alice(30) + Bob(25) = 27.5
                assert avg_age == 27.5
            elif city == "LA":
                # Charlie(35) + David(28) + Eve(32) = 31.67
                assert abs(avg_age - 31.666666666666668) < 0.01
    
    def test_count_with_where(self, query_executor):
        """
        GIVEN: A graph with people of various ages
        WHEN: Executing MATCH (n:Person) WHERE n.age > 30 RETURN COUNT(n)
        THEN: Returns count of people over 30
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) WHERE n.age > 30 RETURN COUNT(n)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        count = records[0][0]
        # Charlie(35) and Eve(32) are over 30
        assert count == 2
    
    def test_multiple_aggregations(self, query_executor):
        """
        GIVEN: A graph with people
        WHEN: Executing MATCH (n:Person) RETURN COUNT(n), AVG(n.age), MAX(n.age)
        THEN: Returns all three aggregation results
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN COUNT(n), AVG(n.age), MAX(n.age)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        record = records[0]
        
        # Should have 3 values
        assert len(record._values) == 3
        assert 5 in record._values    # COUNT
        assert 30.0 in record._values # AVG
        assert 35 in record._values   # MAX


class TestAggregationEdgeCases:
    """Test edge cases for aggregations."""
    
    @pytest.fixture
    def query_executor(self):
        """Create empty QueryExecutor."""
        graph_engine = GraphEngine()
        return QueryExecutor(graph_engine=graph_engine), graph_engine
    
    def test_count_on_empty_graph(self, query_executor):
        """
        GIVEN: An empty graph
        WHEN: Executing COUNT
        THEN: Returns 0
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN COUNT(n)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        assert records[0][0] == 0
    
    def test_sum_with_no_numeric_values(self, query_executor):
        """
        GIVEN: A graph with non-numeric properties
        WHEN: Executing SUM on non-numeric property
        THEN: Returns 0 or handles gracefully
        """
        # GIVEN
        executor, engine = query_executor
        engine.create_node(labels=["Person"], properties={"name": "Alice"})
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN SUM(n.name)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        # Should return 0 for non-numeric
        assert records[0][0] == 0
    
    def test_avg_with_null_values(self, query_executor):
        """
        GIVEN: A graph where some nodes lack the property
        WHEN: Executing AVG
        THEN: Ignores null values correctly
        """
        # GIVEN
        executor, engine = query_executor
        engine.create_node(labels=["Person"], properties={"name": "Alice", "age": 30})
        engine.create_node(labels=["Person"], properties={"name": "Bob"})  # No age
        engine.create_node(labels=["Person"], properties={"name": "Charlie", "age": 40})
        
        # WHEN
        result = executor.execute("MATCH (n:Person) RETURN AVG(n.age)")
        
        # THEN
        records = list(result)
        assert len(records) == 1
        # Should average only 30 and 40, ignoring null
        assert records[0][0] == 35.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
