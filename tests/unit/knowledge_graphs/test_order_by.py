"""
Test suite for ORDER BY functionality in Cypher queries.
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.knowledge_graphs.core import QueryExecutor, GraphEngine


class TestOrderBy:
    """Test ORDER BY clause in Cypher queries."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.engine = GraphEngine()
        self.executor = QueryExecutor(self.engine)
        
        # Create test data
        self.alice = self.engine.create_node(
            labels=["Person"],
            properties={"name": "Alice", "age": 30, "city": "NYC"}
        )
        self.bob = self.engine.create_node(
            labels=["Person"],
            properties={"name": "Bob", "age": 25, "city": "LA"}
        )
        self.charlie = self.engine.create_node(
            labels=["Person"],
            properties={"name": "Charlie", "age": 35, "city": "NYC"}
        )
        self.david = self.engine.create_node(
            labels=["Person"],
            properties={"name": "David", "age": 28, "city": "SF"}
        )
    
    def test_order_by_ascending(self):
        """Test ORDER BY with ascending order."""
        query = "MATCH (n:Person) RETURN n.name, n.age ORDER BY n.age"
        result = self.executor.execute(query)
        
        assert len(result) == 4
        # Should be ordered: Bob(25), David(28), Alice(30), Charlie(35)
        assert result[0].get("n.age") == 25
        assert result[1].get("n.age") == 28
        assert result[2].get("n.age") == 30
        assert result[3].get("n.age") == 35
    
    def test_order_by_descending(self):
        """Test ORDER BY with DESC."""
        query = "MATCH (n:Person) RETURN n.name, n.age ORDER BY n.age DESC"
        result = self.executor.execute(query)
        
        assert len(result) == 4
        # Should be ordered: Charlie(35), Alice(30), David(28), Bob(25)
        assert result[0].get("n.age") == 35
        assert result[1].get("n.age") == 30
        assert result[2].get("n.age") == 28
        assert result[3].get("n.age") == 25
    
    def test_order_by_string(self):
        """Test ORDER BY with string values."""
        query = "MATCH (n:Person) RETURN n.name ORDER BY n.name"
        result = self.executor.execute(query)
        
        assert len(result) == 4
        # Alphabetical order
        names = [r.get("n.name") for r in result]
        assert names == ["Alice", "Bob", "Charlie", "David"]
    
    def test_order_by_multiple_columns(self):
        """Test ORDER BY with multiple expressions."""
        query = "MATCH (n:Person) RETURN n.city, n.name, n.age ORDER BY n.city, n.age"
        result = self.executor.execute(query)
        
        assert len(result) == 4
        # Should be ordered by city first, then by age within each city
        # LA: Bob(25)
        # NYC: Alice(30), Charlie(35)
        # SF: David(28)
        cities = [r.get("n.city") for r in result]
        assert cities[0] == "LA"  # Bob
        assert cities[1] == "NYC"  # Alice
        assert cities[2] == "NYC"  # Charlie
        assert cities[3] == "SF"  # David
    
    def test_order_by_with_limit(self):
        """Test ORDER BY combined with LIMIT."""
        query = "MATCH (n:Person) RETURN n.name, n.age ORDER BY n.age LIMIT 2"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        # Should return youngest two: Bob(25), David(28)
        assert result[0].get("n.age") == 25
        assert result[1].get("n.age") == 28
    
    def test_order_by_with_skip(self):
        """Test ORDER BY combined with SKIP."""
        query = "MATCH (n:Person) RETURN n.name, n.age ORDER BY n.age SKIP 2"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        # Should skip first two and return: Alice(30), Charlie(35)
        assert result[0].get("n.age") == 30
        assert result[1].get("n.age") == 35
    
    def test_order_by_with_skip_and_limit(self):
        """Test ORDER BY with both SKIP and LIMIT."""
        query = "MATCH (n:Person) RETURN n.name, n.age ORDER BY n.age SKIP 1 LIMIT 2"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        # Should skip first one and take next two: David(28), Alice(30)
        assert result[0].get("n.age") == 28
        assert result[1].get("n.age") == 30
    
    def test_order_by_with_aggregation(self):
        """Test ORDER BY with COUNT aggregation."""
        query = """
        MATCH (n:Person)
        RETURN n.city, COUNT(n) AS count
        ORDER BY count DESC
        """
        result = self.executor.execute(query)
        
        assert len(result) == 3
        # NYC has 2 people, others have 1 each
        # Should be ordered: NYC(2), LA(1), SF(1) or SF(1), LA(1) (ties)
        assert result[0].get("count") == 2
        assert result[1].get("count") == 1
        assert result[2].get("count") == 1
    
    def test_order_by_empty_result(self):
        """Test ORDER BY with no results."""
        query = "MATCH (n:NonExistent) RETURN n ORDER BY n.value"
        result = self.executor.execute(query)
        
        assert len(result) == 0
    
    def test_order_by_with_null_values(self):
        """Test ORDER BY with NULL values."""
        # Create a person without age
        eve = self.engine.create_node(
            labels=["Person"],
            properties={"name": "Eve", "city": "Boston"}
        )
        
        query = "MATCH (n:Person) RETURN n.name, n.age ORDER BY n.age"
        result = self.executor.execute(query)
        
        assert len(result) == 5
        # NULL values should sort to the end
        # Ages should be: 25, 28, 30, 35, None
        assert result[0].get("n.age") == 25
        assert result[1].get("n.age") == 28
        assert result[2].get("n.age") == 30
        assert result[3].get("n.age") == 35
        # Last one should be Eve with None/null age
        assert result[4].get("n.name") == "Eve"


class TestOrderByIntegration:
    """Integration tests for ORDER BY with other features."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.engine = GraphEngine()
        self.executor = QueryExecutor(self.engine)
    
    def test_order_by_with_where(self):
        """Test ORDER BY with WHERE clause."""
        # Create test data
        for i in range(5):
            self.engine.create_node(
                labels=["Number"],
                properties={"value": i * 10}
            )
        
        query = "MATCH (n:Number) WHERE n.value > 10 RETURN n.value ORDER BY n.value DESC"
        result = self.executor.execute(query)
        
        assert len(result) == 3
        # Should return 40, 30, 20 (values > 10 in descending order)
        assert result[0].get("n.value") == 40
        assert result[1].get("n.value") == 30
        assert result[2].get("n.value") == 20
    
    def test_order_by_complex_query(self):
        """Test ORDER BY in a complex query with relationships."""
        # Create graph: A knows B, B knows C
        a = self.engine.create_node(labels=["Person"], properties={"name": "A", "age": 30})
        b = self.engine.create_node(labels=["Person"], properties={"name": "B", "age": 25})
        c = self.engine.create_node(labels=["Person"], properties={"name": "C", "age": 35})
        
        self.engine.create_relationship("KNOWS", a.id, b.id)
        self.engine.create_relationship("KNOWS", b.id, c.id)
        
        query = """
        MATCH (n:Person)-[:KNOWS]->(f:Person)
        RETURN n.name, f.name, f.age
        ORDER BY f.age
        """
        result = self.executor.execute(query)
        
        assert len(result) == 2
        # Should be ordered by friend's age: B(25), C(35)
        assert result[0].get("f.age") == 25
        assert result[1].get("f.age") == 35


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
