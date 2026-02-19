"""Protocol definitions for MCP server interfaces.

This module defines Protocol classes (PEP 544) to break circular dependencies
and provide clear interfaces for different MCP server components.

Created as part of Phase 2 Week 4: Circular Dependency Elimination
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Protocol, runtime_checkable


@runtime_checkable
class MCPServerProtocol(Protocol):
    """Protocol for MCP server instances used by P2P adapters.
    
    This protocol defines the minimal interface needed by P2PMCPRegistryAdapter
    without requiring a full import of the server module.
    """
    
    tools: Dict[str, Callable[..., Any]]
    """Dictionary mapping tool names to callable functions."""
    
    def validate_p2p_token(self, token: str) -> bool:
        """Validate a P2P authentication token.
        
        Args:
            token: The token to validate
            
        Returns:
            True if token is valid, False otherwise
        """
        ...


@runtime_checkable
class ToolManagerProtocol(Protocol):
    """Protocol for hierarchical tool managers.
    
    Defines the interface for tool managers that organize tools into categories
    and provide meta-tools for discovery and dispatch.
    """
    
    def list_categories(self) -> list[str]:
        """List all tool categories.
        
        Returns:
            List of category names
        """
        ...
    
    def list_tools(self, category: str | None = None) -> list[Dict[str, Any]]:
        """List tools, optionally filtered by category.
        
        Args:
            category: Optional category filter
            
        Returns:
            List of tool descriptors
        """
        ...
    
    def get_schema(self, tool_name: str) -> Dict[str, Any]:
        """Get schema for a specific tool.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool schema including input parameters
        """
        ...
    
    def dispatch(self, tool_name: str, **kwargs: Any) -> Any:
        """Dispatch a tool execution.
        
        Args:
            tool_name: Name of the tool to execute
            **kwargs: Tool parameters
            
        Returns:
            Tool execution result
        """
        ...


@runtime_checkable
class MCPClientProtocol(Protocol):
    """Protocol for MCP client implementations.
    
    Defines the interface for MCP clients that can register tools
    and communicate with MCP servers.
    """
    
    def add_tool(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Register a tool with the MCP client.
        
        Args:
            func: The tool function to register
            name: Optional tool name (defaults to function name)
            description: Optional tool description
        """
        ...
    
    def list_tools(self) -> list[Dict[str, Any]]:
        """List all registered tools.
        
        Returns:
            List of tool descriptors
        """
        ...


@runtime_checkable
class P2PServiceProtocol(Protocol):
    """Protocol for P2P service managers.
    
    Defines the interface for P2P services that manage distributed
    tool execution and registration.
    """
    
    def start(self) -> None:
        """Start the P2P service."""
        ...
    
    def stop(self) -> None:
        """Stop the P2P service."""
        ...
    
    def is_running(self) -> bool:
        """Check if P2P service is running.
        
        Returns:
            True if running, False otherwise
        """
        ...
    
    def register_tool(self, name: str, func: Callable[..., Any]) -> None:
        """Register a tool with the P2P service.
        
        Args:
            name: Tool name
            func: Tool function
        """
        ...


# Type aliases for common patterns
ToolDict = Dict[str, Callable[..., Any]]
ToolDescriptor = Dict[str, Any]
ToolRegistry = Dict[str, ToolDescriptor]


def check_protocol_implementation(
    obj: Any,
    protocol: type,
    strict: bool = False,
) -> bool:
    """Check if an object implements a protocol.
    
    Args:
        obj: Object to check
        protocol: Protocol class to check against
        strict: If True, raise TypeError on failure. If False, return bool.
        
    Returns:
        True if object implements protocol, False otherwise
        
    Raises:
        TypeError: If strict=True and object doesn't implement protocol
    """
    implements = isinstance(obj, protocol)
    
    if strict and not implements:
        raise TypeError(
            f"Object {type(obj).__name__} does not implement "
            f"{protocol.__name__} protocol"
        )
    
    return implements
