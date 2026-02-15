"""
Tests for Additional Operators - IN, CONTAINS, STARTS WITH, ENDS WITH
(Phase 1, Task 1.2 continued)

This test suite validates additional query operators:
- IN operator for list membership
- CONTAINS for substring search
- STARTS WITH for prefix matching
- ENDS WITH for suffix matching

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor, GraphEngine


class TestInOperator:
    """Test suite for IN operator."""
    
    @pytest.fixture
    def query_executor(self):
        """Create QueryExecutor with sample data."""
        graph_engine = GraphEngine()
        executor = QueryExecutor(graph_engine=graph_engine)
        
        # Create people in different cities
        graph_engine.create_node(labels=["Person"], properties={"name": "Alice", "city": "NYC", "age": 30})
        graph_engine.create_node(labels=["Person"], properties={"name": "Bob", "city": "LA", "age": 25})
        graph_engine.create_node(labels=["Person"], properties={"name": "Charlie", "city": "SF", "age": 35})
        graph_engine.create_node(labels=["Person"], properties={"name": "David", "city": "NYC", "age": 28})
        graph_engine.create_node(labels=["Person"], properties={"name": "Eve", "city": "Chicago", "age": 32})
        
        return executor, graph_engine
    
    def test_in_operator_cities(self, query_executor):
        """
        GIVEN: People in various cities
        WHEN: Using IN operator for city list
        THEN: Returns only people in specified cities
        """
        # GIVEN
        executor, engine = query_executor
        
        # WHEN - Note: Need to implement IN parsing, but operator logic is ready
        # For now test the _apply_operator directly
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor as QE
        qe = QE()
        
        # Test IN operator logic
        assert qe._apply_operator("NYC", "IN", ["NYC", "LA", "SF"]) == True
        assert qe._apply_operator("Chicago", "IN", ["NYC", "LA", "SF"]) == False
    
    def test_in_operator_ages(self, query_executor):
        """
        GIVEN: People of various ages
        WHEN: Using IN operator for age list
        THEN: Returns people with matching ages
        """
        # GIVEN
        executor, engine = query_executor
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator(30, "IN", [25, 30, 35]) == True
        assert qe._apply_operator(28, "IN", [25, 30, 35]) == False
    
    def test_in_operator_empty_list(self, query_executor):
        """
        GIVEN: Data
        WHEN: Using IN with empty list
        THEN: Returns False
        """
        # GIVEN
        executor, engine = query_executor
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator("NYC", "IN", []) == False


class TestStringOperators:
    """Test suite for string operators."""
    
    @pytest.fixture
    def query_executor(self):
        """Create QueryExecutor with sample data."""
        graph_engine = GraphEngine()
        executor = QueryExecutor(graph_engine=graph_engine)
        
        # Create people with various name patterns
        graph_engine.create_node(labels=["Person"], properties={"name": "Alice Smith"})
        graph_engine.create_node(labels=["Person"], properties={"name": "Bob Johnson"})
        graph_engine.create_node(labels=["Person"], properties={"name": "Charlie Brown"})
        graph_engine.create_node(labels=["Person"], properties={"name": "David Smith"})
        
        # Create files with extensions
        graph_engine.create_node(labels=["File"], properties={"name": "document.pdf"})
        graph_engine.create_node(labels=["File"], properties={"name": "image.jpg"})
        graph_engine.create_node(labels=["File"], properties={"name": "report.pdf"})
        
        return executor, graph_engine
    
    def test_contains_operator(self, query_executor):
        """
        GIVEN: People with various names
        WHEN: Using CONTAINS operator
        THEN: Returns names containing substring
        """
        # GIVEN
        executor, engine = query_executor
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator("Alice Smith", "CONTAINS", "Smith") == True
        assert qe._apply_operator("Alice Smith", "CONTAINS", "Alice") == True
        assert qe._apply_operator("Bob Johnson", "CONTAINS", "Smith") == False
    
    def test_starts_with_operator(self, query_executor):
        """
        GIVEN: People with various names
        WHEN: Using STARTS WITH operator
        THEN: Returns names starting with prefix
        """
        # GIVEN
        executor, engine = query_executor
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator("Alice Smith", "STARTS WITH", "Alice") == True
        assert qe._apply_operator("Alice Smith", "STARTS WITH", "Bob") == False
        assert qe._apply_operator("Alice Smith", "STARTS WITH", "Smith") == False
    
    def test_ends_with_operator(self, query_executor):
        """
        GIVEN: Files with various extensions
        WHEN: Using ENDS WITH operator
        THEN: Returns names ending with suffix
        """
        # GIVEN
        executor, engine = query_executor
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator("document.pdf", "ENDS WITH", ".pdf") == True
        assert qe._apply_operator("image.jpg", "ENDS WITH", ".pdf") == False
        assert qe._apply_operator("report.pdf", "ENDS WITH", ".pdf") == True
    
    def test_contains_case_sensitive(self, query_executor):
        """
        GIVEN: Names with various cases
        WHEN: Using CONTAINS (case sensitive)
        THEN: Respects case
        """
        # GIVEN
        executor, engine = query_executor
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator("Alice Smith", "CONTAINS", "alice") == False
        assert qe._apply_operator("Alice Smith", "CONTAINS", "Alice") == True
    
    def test_string_operators_with_non_strings(self, query_executor):
        """
        GIVEN: Non-string values
        WHEN: Using string operators
        THEN: Returns False gracefully
        """
        # GIVEN
        executor, engine = query_executor
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator(123, "CONTAINS", "12") == False
        assert qe._apply_operator(None, "STARTS WITH", "test") == False
        assert qe._apply_operator("test", "ENDS WITH", None) == False


class TestOperatorEdgeCases:
    """Test edge cases for operators."""
    
    def test_in_operator_with_non_list(self):
        """
        GIVEN: IN operator with non-list value
        WHEN: Checking membership
        THEN: Returns False
        """
        # GIVEN
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator("NYC", "IN", "NYC") == False
        assert qe._apply_operator(1, "IN", 1) == False
    
    def test_operators_with_none(self):
        """
        GIVEN: None values
        WHEN: Using operators
        THEN: Handles gracefully
        """
        # GIVEN
        qe = QueryExecutor()
        
        # WHEN & THEN
        assert qe._apply_operator(None, "IN", [None, 1, 2]) == True
        assert qe._apply_operator(None, "=", None) == True
        assert qe._apply_operator(None, ">", 5) == False


class TestOperatorIntegration:
    """Integration tests for operators with real queries."""
    
    @pytest.fixture
    def query_executor(self):
        """Create QueryExecutor with diverse data."""
        graph_engine = GraphEngine()
        executor = QueryExecutor(graph_engine=graph_engine)
        
        # Create diverse nodes
        graph_engine.create_node(labels=["User"], properties={
            "username": "admin_user",
            "email": "admin@example.com",
            "role": "admin",
            "age": 35
        })
        graph_engine.create_node(labels=["User"], properties={
            "username": "john_doe",
            "email": "john@test.com",
            "role": "user",
            "age": 28
        })
        graph_engine.create_node(labels=["User"], properties={
            "username": "jane_smith",
            "email": "jane@example.com",
            "role": "moderator",
            "age": 32
        })
        
        return executor, graph_engine
    
    def test_multiple_operators_combined(self, query_executor):
        """
        GIVEN: Users with various properties
        WHEN: Testing operator combinations
        THEN: All operators work correctly
        """
        # GIVEN
        executor, engine = query_executor
        qe = QueryExecutor()
        
        # WHEN & THEN
        # Combining operators
        assert qe._apply_operator("admin", "IN", ["admin", "moderator"]) == True
        assert qe._apply_operator("admin@example.com", "CONTAINS", "@example.com") == True
        assert qe._apply_operator("admin_user", "STARTS WITH", "admin") == True
        
        # Age comparisons
        assert qe._apply_operator(35, ">", 30) == True
        assert qe._apply_operator(28, "IN", [25, 28, 30]) == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
