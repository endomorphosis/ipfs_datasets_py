"""Custom exceptions for MCP server operations.

This module defines a hierarchy of custom exceptions to replace broad
`except Exception` handlers with specific, meaningful error types that
improve debugging, logging, and error handling throughout the MCP server.
"""

from typing import Optional, Dict, Any


class MCPServerError(Exception):
    """Base exception for all MCP server errors.
    
    All custom MCP server exceptions inherit from this base class,
    allowing for broad exception handling when needed while still
    maintaining specific exception types for detailed error handling.
    
    Attributes:
        message: Human-readable error message
        details: Optional dictionary with additional error context
    """
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Initialise with a human-readable message and optional detail dict.

        Args:
            message: Human-readable description of the error.
            details: Optional mapping of additional context (e.g. tool name, field).
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Return message with flattened details appended in parentheses."""
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({details_str})"
        return self.message


# Tool-related exceptions

class ToolError(MCPServerError):
    """Base exception for tool-related errors."""
    pass


class ToolNotFoundError(ToolError):
    """Raised when a requested tool cannot be found."""
    
    def __init__(self, tool_name: str, category: Optional[str] = None) -> None:
        """Initialise with the missing tool name and optional category.

        Args:
            tool_name: Name of the tool that could not be found.
            category: Category prefix, if the lookup was qualified.
        """
        self.tool_name = tool_name
        self.category = category
        message = f"Tool not found: {tool_name}"
        if category:
            message = f"Tool not found: {category}.{tool_name}"
        super().__init__(message, {"tool_name": tool_name, "category": category})


class ToolExecutionError(ToolError):
    """Raised when tool execution fails."""
    
    def __init__(self, tool_name: str, original_error: Exception) -> None:
        """Initialise with the tool name and the underlying cause.

        Args:
            tool_name: Name of the tool that failed.
            original_error: The exception raised during execution.
        """
        self.tool_name = tool_name
        self.original_error = original_error
        message = f"Tool execution failed: {tool_name} - {str(original_error)}"
        super().__init__(message, {"tool_name": tool_name, "error_type": type(original_error).__name__})
        self.__cause__ = original_error


class ToolRegistrationError(ToolError):
    """Raised when tool registration fails."""
    pass


# Validation exceptions

class ValidationError(MCPServerError):
    """Raised when input validation fails."""
    
    def __init__(self, field: str, message: str) -> None:
        """Initialise with the field name and a description of the violation.

        Args:
            field: Name of the input field that failed validation.
            message: Description of why validation failed.
        """
        self.field = field
        super().__init__(f"Validation error for '{field}': {message}", {"field": field})


# Runtime routing exceptions

class RuntimeRoutingError(MCPServerError):
    """Base exception for runtime routing errors."""
    pass


class RuntimeNotFoundError(RuntimeRoutingError):
    """Raised when requested runtime is not available."""
    
    def __init__(self, runtime: str) -> None:
        """Initialise with the name of the unavailable runtime.

        Args:
            runtime: Identifier of the runtime that was not found.
        """
        self.runtime = runtime
        super().__init__(f"Runtime not found: {runtime}", {"runtime": runtime})


class RuntimeExecutionError(RuntimeRoutingError):
    """Raised when runtime execution fails."""
    pass


# P2P service exceptions

class P2PServiceError(MCPServerError):
    """Base exception for P2P service errors."""
    pass


class P2PConnectionError(P2PServiceError):
    """Raised when P2P connection fails."""
    pass


class P2PAuthenticationError(P2PServiceError):
    """Raised when P2P authentication fails."""
    pass


# Configuration exceptions

class ConfigurationError(MCPServerError):
    """Raised when configuration is invalid or missing."""
    pass


# Server lifecycle exceptions

class ServerStartupError(MCPServerError):
    """Raised when server startup fails."""
    pass


class ServerShutdownError(MCPServerError):
    """Raised when server shutdown fails."""
    pass


# Health check exceptions

class HealthCheckError(MCPServerError):
    """Raised when health check fails."""
    
    def __init__(self, check_name: str, message: str) -> None:
        """Initialise with the health-check name and a failure description.

        Args:
            check_name: Identifier of the health check that failed.
            message: Human-readable description of the failure.
        """
        self.check_name = check_name
        super().__init__(f"Health check failed: {check_name} - {message}", {"check_name": check_name})


# Monitoring exceptions

class MonitoringError(MCPServerError):
    """Base exception for monitoring system errors."""
    pass


class MetricsCollectionError(MonitoringError):
    """Raised when metrics collection fails."""
    pass


__all__ = [
    # Base
    'MCPServerError',
    # Tool
    'ToolError',
    'ToolNotFoundError',
    'ToolExecutionError',
    'ToolRegistrationError',
    # Validation
    'ValidationError',
    # Runtime
    'RuntimeRoutingError',
    'RuntimeNotFoundError',
    'RuntimeExecutionError',
    # P2P
    'P2PServiceError',
    'P2PConnectionError',
    'P2PAuthenticationError',
    # Configuration
    'ConfigurationError',
    # Server
    'ServerStartupError',
    'ServerShutdownError',
    # Health
    'HealthCheckError',
    # Monitoring
    'MonitoringError',
    'MetricsCollectionError',
]
