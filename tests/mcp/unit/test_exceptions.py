"""Tests for MCP server custom exceptions module."""

import pytest
from ipfs_datasets_py.mcp_server.exceptions import (
    MCPServerError,
    ToolError,
    ToolNotFoundError,
    ToolExecutionError,
    ToolRegistrationError,
    ValidationError,
    RuntimeRoutingError,
    RuntimeNotFoundError,
    RuntimeExecutionError,
    P2PServiceError,
    P2PConnectionError,
    P2PAuthenticationError,
    ConfigurationError,
    ServerStartupError,
    ServerShutdownError,
    HealthCheckError,
    MonitoringError,
    MetricsCollectionError,
)


def test_base_exception():
    """Test MCPServerError base exception."""
    error = MCPServerError("Test error")
    assert str(error) == "Test error"
    assert error.message == "Test error"
    assert error.details == {}


def test_base_exception_with_details():
    """Test MCPServerError with details."""
    error = MCPServerError("Test error", {"key": "value", "count": 42})
    assert "Test error" in str(error)
    assert "key=value" in str(error)
    assert "count=42" in str(error)
    assert error.details["key"] == "value"
    assert error.details["count"] == 42


def test_tool_not_found_error():
    """Test ToolNotFoundError."""
    error = ToolNotFoundError("ipfs_add")
    assert "ipfs_add" in str(error)
    assert error.tool_name == "ipfs_add"
    assert error.category is None


def test_tool_not_found_error_with_category():
    """Test ToolNotFoundError with category."""
    error = ToolNotFoundError("ipfs_add", "ipfs_tools")
    assert "ipfs_tools.ipfs_add" in str(error)
    assert error.tool_name == "ipfs_add"
    assert error.category == "ipfs_tools"


def test_tool_execution_error():
    """Test ToolExecutionError with chained exception."""
    original = ValueError("Invalid parameter")
    error = ToolExecutionError("my_tool", original)
    
    assert "my_tool" in str(error)
    assert error.tool_name == "my_tool"
    assert error.original_error is original
    assert error.__cause__ is original
    assert error.details["error_type"] == "ValueError"


def test_validation_error():
    """Test ValidationError."""
    error = ValidationError("email", "Invalid email format")
    assert "email" in str(error)
    assert "Invalid email format" in str(error)
    assert error.field == "email"


def test_runtime_not_found_error():
    """Test RuntimeNotFoundError."""
    error = RuntimeNotFoundError("trio")
    assert "trio" in str(error)
    assert error.runtime == "trio"


def test_health_check_error():
    """Test HealthCheckError."""
    error = HealthCheckError("database", "Connection timeout")
    assert "database" in str(error)
    assert "Connection timeout" in str(error)
    assert error.check_name == "database"


def test_exception_hierarchy():
    """Test exception inheritance hierarchy."""
    # All custom exceptions inherit from MCPServerError
    assert issubclass(ToolError, MCPServerError)
    assert issubclass(ToolNotFoundError, ToolError)
    assert issubclass(ToolExecutionError, ToolError)
    assert issubclass(ValidationError, MCPServerError)
    assert issubclass(RuntimeRoutingError, MCPServerError)
    assert issubclass(P2PServiceError, MCPServerError)
    assert issubclass(ConfigurationError, MCPServerError)
    
    # Can catch specific exceptions
    try:
        raise ToolNotFoundError("test_tool")
    except ToolError:
        pass  # Should catch
    
    # Can catch all MCP exceptions
    try:
        raise MetricsCollectionError("Test")
    except MCPServerError:
        pass  # Should catch


def test_exception_can_be_raised_and_caught():
    """Test that exceptions can be raised and caught properly."""
    with pytest.raises(ToolNotFoundError) as exc_info:
        raise ToolNotFoundError("missing_tool", "tools")
    
    assert exc_info.value.tool_name == "missing_tool"
    assert exc_info.value.category == "tools"


def test_all_exceptions_importable():
    """Test that all exceptions can be imported."""
    # This test verifies __all__ exports
    from ipfs_datasets_py.mcp_server import exceptions
    
    for exc_name in exceptions.__all__:
        assert hasattr(exceptions, exc_name)
        exc_class = getattr(exceptions, exc_name)
        assert issubclass(exc_class, Exception)
