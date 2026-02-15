"""
Test suite for string functions in Cypher queries.
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine


class TestStringFunctions:
    """Test string manipulation functions in Cypher."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.engine = GraphEngine()
        self.executor = QueryExecutor(self.engine)
        
        # Create test data with various strings
        self.engine.create_node(
            labels=["User"],
            properties={
                "name": "Alice Smith",
                "email": "ALICE@EXAMPLE.COM",
                "username": "  alice123  ",
                "bio": "Hello World",
                "code": "ABC-123"
            }
        )
        self.engine.create_node(
            labels=["User"],
            properties={
                "name": "Bob Jones",
                "email": "bob@test.org",
                "username": "bob_admin",
                "bio": "Testing 123",
                "code": "XYZ-456"
            }
        )
    
    def test_tolower_function(self):
        """Test toLower() function."""
        query = "MATCH (n:User) RETURN toLower(n.email) AS lower_email"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        emails = [r.get("lower_email") for r in result]
        assert "alice@example.com" in emails
        assert "bob@test.org" in emails
    
    def test_toupper_function(self):
        """Test toUpper() function."""
        query = "MATCH (n:User) RETURN toUpper(n.name) AS upper_name"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        names = [r.get("upper_name") for r in result]
        assert "ALICE SMITH" in names
        assert "BOB JONES" in names
    
    def test_tolower_in_where_clause(self):
        """Test toLower() in WHERE clause for case-insensitive search."""
        query = """
        MATCH (n:User)
        WHERE toLower(n.email) CONTAINS 'alice'
        RETURN n.name
        """
        result = self.executor.execute(query)
        
        assert len(result) == 1
        assert result[0].get("n.name") == "Alice Smith"
    
    def test_substring_function(self):
        """Test substring() function."""
        query = "MATCH (n:User) RETURN substring(n.email, 0, 5) AS prefix"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        prefixes = [r.get("prefix") for r in result]
        assert "ALICE" in prefixes
        assert "bob@t" in prefixes
    
    def test_substring_with_length(self):
        """Test substring() with start and length."""
        query = "MATCH (n:User) WHERE n.name = 'Alice Smith' RETURN substring(n.name, 0, 5) AS first"
        result = self.executor.execute(query)
        
        assert len(result) == 1
        assert result[0].get("first") == "Alice"
    
    def test_substring_from_position(self):
        """Test substring() from position to end."""
        query = "MATCH (n:User) WHERE n.name = 'Alice Smith' RETURN substring(n.name, 6) AS last"
        result = self.executor.execute(query)
        
        assert len(result) == 1
        assert result[0].get("last") == "Smith"
    
    def test_trim_function(self):
        """Test trim() function."""
        query = "MATCH (n:User) RETURN trim(n.username) AS trimmed"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        usernames = [r.get("trimmed") for r in result]
        assert "alice123" in usernames
        assert "bob_admin" in usernames
    
    def test_replace_function(self):
        """Test replace() function."""
        query = "MATCH (n:User) RETURN replace(n.bio, 'World', 'Universe') AS new_bio"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        bios = [r.get("new_bio") for r in result]
        assert "Hello Universe" in bios
        assert "Testing 123" in bios
    
    def test_replace_with_special_chars(self):
        """Test replace() with special characters."""
        query = "MATCH (n:User) RETURN replace(n.code, '-', '_') AS new_code"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        codes = [r.get("new_code") for r in result]
        assert "ABC_123" in codes
        assert "XYZ_456" in codes
    
    def test_size_function_string(self):
        """Test size() function with strings."""
        query = "MATCH (n:User) WHERE n.name = 'Bob Jones' RETURN size(n.name) AS name_length"
        result = self.executor.execute(query)
        
        assert len(result) == 1
        assert result[0].get("name_length") == 9  # "Bob Jones"
    
    def test_reverse_function(self):
        """Test reverse() function."""
        query = "MATCH (n:User) WHERE n.name = 'Alice Smith' RETURN reverse(n.name) AS reversed"
        result = self.executor.execute(query)
        
        assert len(result) == 1
        assert result[0].get("reversed") == "htimS ecilA"
    
    def test_split_function(self):
        """Test split() function."""
        query = "MATCH (n:User) WHERE n.name = 'Alice Smith' RETURN split(n.name, ' ') AS parts"
        result = self.executor.execute(query)
        
        assert len(result) == 1
        parts = result[0].get("parts")
        assert isinstance(parts, list)
        assert parts == ["Alice", "Smith"]
    
    def test_split_with_delimiter(self):
        """Test split() with custom delimiter."""
        query = "MATCH (n:User) RETURN split(n.code, '-') AS code_parts"
        result = self.executor.execute(query)
        
        assert len(result) == 2
        for record in result:
            parts = record.get("code_parts")
            assert isinstance(parts, list)
            assert len(parts) == 2
    
    def test_left_function(self):
        """Test left() function."""
        query = "MATCH (n:User) WHERE n.name = 'Alice Smith' RETURN left(n.name, 5) AS first_five"
        result = self.executor.execute(query)
        
        assert len(result) == 1
        assert result[0].get("first_five") == "Alice"
    
    def test_right_function(self):
        """Test right() function."""
        query = "MATCH (n:User) WHERE n.name = 'Alice Smith' RETURN right(n.name, 5) AS last_five"
        result = self.executor.execute(query)
        
        assert len(result) == 1
        assert result[0].get("last_five") == "Smith"
    
    def test_multiple_string_functions(self):
        """Test combining multiple string functions."""
        query = """
        MATCH (n:User)
        RETURN 
            toUpper(trim(n.username)) AS cleaned,
            size(n.name) AS name_len
        """
        result = self.executor.execute(query)
        
        assert len(result) == 2
        for record in result:
            cleaned = record.get("cleaned")
            name_len = record.get("name_len")
            assert cleaned is not None
            assert name_len > 0
    
    def test_string_function_with_null(self):
        """Test string functions with NULL values."""
        # Create node without some properties
        self.engine.create_node(
            labels=["User"],
            properties={"name": "Charlie"}
        )
        
        query = "MATCH (n:User) WHERE n.name = 'Charlie' RETURN toLower(n.email) AS email"
        result = self.executor.execute(query)
        
        assert len(result) == 1
        assert result[0].get("email") is None
    
    def test_nested_string_functions(self):
        """Test nested string function calls."""
        query = """
        MATCH (n:User)
        WHERE n.name = 'Alice Smith'
        RETURN toUpper(trim(n.username)) AS result
        """
        result = self.executor.execute(query)
        
        assert len(result) == 1
        # Should trim first, then convert to upper
        assert result[0].get("result") == "ALICE123"


class TestStringFunctionsIntegration:
    """Integration tests for string functions with other features."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.engine = GraphEngine()
        self.executor = QueryExecutor(self.engine)
    
    def test_string_functions_with_order_by(self):
        """Test string functions in ORDER BY."""
        self.engine.create_node(labels=["Item"], properties={"name": "Zebra"})
        self.engine.create_node(labels=["Item"], properties={"name": "apple"})
        self.engine.create_node(labels=["Item"], properties={"name": "Banana"})
        
        query = "MATCH (n:Item) RETURN n.name ORDER BY toLower(n.name)"
        result = self.executor.execute(query)
        
        assert len(result) == 3
        names = [r.get("n.name") for r in result]
        # Case-insensitive alphabetical order
        assert names[0] == "apple"
        assert names[1] == "Banana"
        assert names[2] == "Zebra"
    
    def test_string_functions_with_aggregation(self):
        """Test string functions with aggregation."""
        self.engine.create_node(labels=["Word"], properties={"text": "hello"})
        self.engine.create_node(labels=["Word"], properties={"text": "world"})
        self.engine.create_node(labels=["Word"], properties={"text": "test"})
        
        query = """
        MATCH (n:Word)
        RETURN AVG(size(n.text)) AS avg_length, COUNT(n) AS count
        """
        result = self.executor.execute(query)
        
        assert len(result) == 1
        # Average of 5, 5, 4 = 4.67
        assert abs(result[0].get("avg_length") - 4.67) < 0.1
        assert result[0].get("count") == 3
    
    def test_string_functions_complex_query(self):
        """Test string functions in complex query."""
        for i in range(5):
            self.engine.create_node(
                labels=["User"],
                properties={
                    "email": f"user{i}@example.com",
                    "name": f"User {i}"
                }
            )
        
        query = """
        MATCH (n:User)
        WHERE toLower(n.email) CONTAINS '@example.com'
        RETURN substring(n.email, 0, 5) AS prefix, size(n.name) AS name_len
        ORDER BY name_len
        LIMIT 3
        """
        result = self.executor.execute(query)
        
        assert len(result) == 3
        # All should have email prefix starting with "user"
        for record in result:
            prefix = record.get("prefix")
            assert prefix.startswith("user")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
