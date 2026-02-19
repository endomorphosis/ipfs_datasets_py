"""Integration tests for custom exception handling across MCP server modules.

These tests verify that custom exceptions flow correctly through the system
and provide useful context for debugging and monitoring.
"""

import pytest
from ipfs_datasets_py.mcp_server.exceptions import (
    ToolNotFoundError,
    ToolExecutionError,
    RuntimeExecutionError,
    MetricsCollectionError,
)


class TestExceptionIntegration:
    """Test exception handling integration across modules."""
    
    def test_tool_not_found_error_context(self):
        """Test ToolNotFoundError provides useful context."""
        error = ToolNotFoundError("missing_tool", "test_category")
        
        assert error.tool_name == "missing_tool"
        assert error.category == "test_category"
        assert "test_category.missing_tool" in str(error)
        assert error.details["tool_name"] == "missing_tool"
        assert error.details["category"] == "test_category"
    
    def test_tool_execution_error_chaining(self):
        """Test ToolExecutionError chains original exception."""
        original = ValueError("Invalid parameter")
        error = ToolExecutionError("my_tool", original)
        
        assert error.tool_name == "my_tool"
        assert error.original_error is original
        assert error.__cause__ is original
        assert "ValueError" in error.details["error_type"]
    
    def test_runtime_execution_error_message(self):
        """Test RuntimeExecutionError provides clear context."""
        error = RuntimeExecutionError("Failed to execute on trio runtime")
        
        assert "trio runtime" in str(error)
        assert isinstance(error, RuntimeExecutionError)
    
    def test_metrics_collection_error_message(self):
        """Test MetricsCollectionError provides clear context."""
        error = MetricsCollectionError("Failed to collect CPU metrics")
        
        assert "CPU metrics" in str(error)
        assert isinstance(error, MetricsCollectionError)
    
    def test_exception_details_serialization(self):
        """Test that exception details can be serialized for logging."""
        error = ToolNotFoundError("test_tool", "tools")
        
        # Details should be a dict that can be logged
        assert isinstance(error.details, dict)
        assert "tool_name" in error.details
        assert "category" in error.details
        
        # Should be JSON-serializable
        import json
        json_str = json.dumps(error.details)
        assert "test_tool" in json_str


class TestExceptionPropagation:
    """Test that exceptions propagate correctly through call stacks."""
    
    def test_nested_exception_handling(self):
        """Test exception handling in nested calls."""
        def level_3():
            raise ValueError("Original error")
        
        def level_2():
            try:
                level_3()
            except ValueError as e:
                raise ToolExecutionError("level2_tool", e)
        
        def level_1():
            try:
                level_2()
            except ToolExecutionError:
                raise  # Re-raise to test propagation
        
        with pytest.raises(ToolExecutionError) as exc_info:
            level_1()
        
        error = exc_info.value
        assert error.tool_name == "level2_tool"
        assert isinstance(error.__cause__, ValueError)
        assert "Original error" in str(error.__cause__)
    
    def test_exception_context_preservation(self):
        """Test that exception context is preserved through multiple handlers."""
        try:
            try:
                raise ValueError("Inner error")
            except ValueError as e:
                raise ToolExecutionError("inner_tool", e)
        except ToolExecutionError as e:
            # Context should be preserved
            assert e.__cause__ is not None
            assert isinstance(e.__cause__, ValueError)
            assert str(e.__cause__) == "Inner error"


class TestExceptionLoggingIntegration:
    """Test that exceptions integrate well with logging systems."""
    
    def test_exception_str_includes_details(self):
        """Test that str(exception) includes all important details."""
        error = ToolNotFoundError("ipfs_add", "ipfs_tools")
        error_str = str(error)
        
        assert "ipfs_add" in error_str
        assert "ipfs_tools" in error_str
        assert "tool_name" in error_str
        assert "category" in error_str
    
    def test_exception_with_empty_details(self):
        """Test exceptions handle empty details gracefully."""
        error = MetricsCollectionError("Test error")
        
        # Should not raise when converting to string
        error_str = str(error)
        assert "Test error" in error_str
        # Should not have extra parentheses for empty details
        assert error_str == "Test error"
    
    def test_exception_repr_is_useful(self):
        """Test that repr() provides useful debugging info."""
        error = ToolNotFoundError("test_tool", "category")
        repr_str = repr(error)
        
        # Should be a valid Python expression (roughly)
        assert "ToolNotFoundError" in repr_str or "test_tool" in repr_str


class TestExceptionCompatibility:
    """Test that custom exceptions are compatible with standard exception handling."""
    
    def test_catch_by_base_class(self):
        """Test that custom exceptions can be caught by base Exception."""
        try:
            raise ToolNotFoundError("test")
        except Exception as e:
            assert isinstance(e, ToolNotFoundError)
    
    def test_catch_by_specific_type(self):
        """Test that specific exception types can be caught."""
        try:
            raise ToolExecutionError("test", ValueError("original"))
        except ToolExecutionError as e:
            assert e.tool_name == "test"
        except Exception:
            pytest.fail("Should have caught ToolExecutionError")
    
    def test_exception_args_attribute(self):
        """Test that exceptions have standard args attribute."""
        error = ToolNotFoundError("test_tool", "category")
        
        # Standard Exception interface
        assert hasattr(error, 'args')
        assert len(error.args) > 0
        assert isinstance(error.args[0], str)
