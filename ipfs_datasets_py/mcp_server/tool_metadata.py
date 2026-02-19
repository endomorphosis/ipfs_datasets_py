"""
Tool Metadata System for Dual-Runtime MCP Server

This module provides a comprehensive tool metadata system for managing
tool runtime requirements, registration, and validation.

Key Components:
- ToolMetadata: Complete metadata schema for tools
- ToolMetadataRegistry: Central registry for all tool metadata
- tool_metadata decorator: Easy registration via decorators
- Validation utilities for metadata completeness

Usage:
    from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata, get_registry
    
    # Register a tool with metadata
    @tool_metadata(
        runtime="trio",
        requires_p2p=True,
        category="p2p_workflow",
        priority=8
    )
    async def p2p_workflow_submit(workflow: dict) -> str:
        '''Submit a P2P workflow.'''
        ...
    
    # Get tool metadata
    registry = get_registry()
    metadata = registry.get("p2p_workflow_submit")
    print(f"Runtime: {metadata.runtime}")
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Set
import logging
import inspect

logger = logging.getLogger(__name__)

# Runtime constants
RUNTIME_FASTAPI = "fastapi"
RUNTIME_TRIO = "trio"
RUNTIME_AUTO = "auto"


@dataclass
class ToolMetadata:
    """
    Complete metadata for an MCP tool.
    
    Attributes:
        name: Tool name (e.g., "p2p_workflow_submit")
        runtime: Preferred runtime ("fastapi" or "trio")
        requires_p2p: Whether tool requires P2P capabilities
        category: Tool category (e.g., "p2p_workflow", "dataset")
        priority: Execution priority (0-10, higher = more critical)
        timeout_seconds: Maximum execution time
        retry_policy: Retry strategy ("none", "exponential", "linear")
        memory_intensive: Whether tool uses significant memory
        cpu_intensive: Whether tool is CPU-bound
        io_intensive: Whether tool is I/O-bound
        mcp_schema: MCP schema definition
        mcp_description: Tool description for MCP
    
    Example:
        >>> metadata = ToolMetadata(
        ...     name="p2p_workflow_submit",
        ...     runtime="trio",
        ...     requires_p2p=True,
        ...     category="p2p_workflow",
        ...     priority=8
        ... )
    """
    
    name: str
    runtime: str = RUNTIME_AUTO
    requires_p2p: bool = False
    category: str = "general"
    priority: int = 5
    timeout_seconds: Optional[float] = 30.0
    retry_policy: str = "none"
    memory_intensive: bool = False
    cpu_intensive: bool = False
    io_intensive: bool = False
    mcp_schema: Optional[dict] = None
    mcp_description: Optional[str] = None
    
    # Internal attributes
    _func: Optional[Callable] = field(default=None, repr=False, compare=False)
    
    def __post_init__(self) -> None:
        """Validate metadata after initialization."""
        if self.runtime not in (RUNTIME_FASTAPI, RUNTIME_TRIO, RUNTIME_AUTO):
            raise ValueError(f"Invalid runtime: {self.runtime}")
        
        if self.priority < 0 or self.priority > 10:
            raise ValueError(f"Priority must be 0-10, got {self.priority}")
        
        if self.retry_policy not in ("none", "exponential", "linear"):
            raise ValueError(f"Invalid retry_policy: {self.retry_policy}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metadata to dictionary (excluding internal fields)."""
        data = asdict(self)
        data.pop('_func', None)
        return data
    
    def validate_complete(self) -> List[str]:
        """
        Validate metadata completeness.
        
        Returns:
            List of validation warnings (empty if complete)
        """
        warnings = []
        
        if not self.name:
            warnings.append("Tool name is required")
        
        if not self.mcp_description:
            warnings.append("MCP description is recommended")
        
        if not self.mcp_schema:
            warnings.append("MCP schema is recommended")
        
        if self.requires_p2p and self.runtime == RUNTIME_FASTAPI:
            warnings.append("P2P tool should use trio runtime")
        
        return warnings


class ToolMetadataRegistry:
    """
    Central registry for all tool metadata.
    
    This class manages metadata for all tools, provides lookup
    capabilities, and validates registration.
    
    Example:
        >>> registry = ToolMetadataRegistry()
        >>> registry.register(metadata)
        >>> tool_metadata = registry.get("p2p_workflow_submit")
        >>> trio_tools = registry.list_by_runtime("trio")
    """
    
    def __init__(self) -> None:
        """Initialize the registry."""
        self._registry: Dict[str, ToolMetadata] = {}
        self._by_runtime: Dict[str, Set[str]] = {
            RUNTIME_FASTAPI: set(),
            RUNTIME_TRIO: set(),
            RUNTIME_AUTO: set()
        }
        self._by_category: Dict[str, Set[str]] = {}
        
    def register(self, metadata: ToolMetadata) -> None:
        """
        Register tool metadata.
        
        Args:
            metadata: ToolMetadata instance to register
            
        Raises:
            ValueError: If tool already registered with different metadata
        """
        tool_name = metadata.name
        
        # Check for conflicts
        if tool_name in self._registry:
            existing = self._registry[tool_name]
            if existing.runtime != metadata.runtime:
                logger.warning(
                    f"Tool '{tool_name}' re-registered with different runtime: "
                    f"{existing.runtime} -> {metadata.runtime}"
                )
        
        # Register
        self._registry[tool_name] = metadata
        self._by_runtime[metadata.runtime].add(tool_name)
        
        # Track by category
        if metadata.category not in self._by_category:
            self._by_category[metadata.category] = set()
        self._by_category[metadata.category].add(tool_name)
        
        logger.debug(f"Registered tool metadata: {tool_name} (runtime={metadata.runtime})")
    
    def get(self, tool_name: str) -> Optional[ToolMetadata]:
        """
        Get metadata for a tool.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            ToolMetadata instance or None if not found
        """
        return self._registry.get(tool_name)
    
    def list_by_runtime(self, runtime: str) -> List[ToolMetadata]:
        """
        List all tools for a specific runtime.
        
        Args:
            runtime: Runtime identifier
            
        Returns:
            List of ToolMetadata instances
        """
        tool_names = self._by_runtime.get(runtime, set())
        return [self._registry[name] for name in tool_names]
    
    def list_by_category(self, category: str) -> List[ToolMetadata]:
        """
        List all tools in a category.
        
        Args:
            category: Category name
            
        Returns:
            List of ToolMetadata instances
        """
        tool_names = self._by_category.get(category, set())
        return [self._registry[name] for name in tool_names]
    
    def list_all(self) -> List[ToolMetadata]:
        """List all registered tool metadata."""
        return list(self._registry.values())
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get registry statistics.
        
        Returns:
            Dictionary with statistics
        """
        total = len(self._registry)
        return {
            "total_tools": total,
            "by_runtime": {
                runtime: len(tools)
                for runtime, tools in self._by_runtime.items()
            },
            "by_category": {
                category: len(tools)
                for category, tools in self._by_category.items()
            },
            "p2p_tools": sum(
                1 for m in self._registry.values() if m.requires_p2p
            ),
            "categories": len(self._by_category)
        }
    
    def clear(self) -> None:
        """Clear all registered metadata (for testing)."""
        self._registry.clear()
        self._by_runtime = {
            RUNTIME_FASTAPI: set(),
            RUNTIME_TRIO: set(),
            RUNTIME_AUTO: set()
        }
        self._by_category.clear()


# Global registry instance (deprecated - use ServerContext instead)
_global_registry = ToolMetadataRegistry()


def get_registry(context: Optional["ServerContext"] = None) -> ToolMetadataRegistry:
    """Get the tool metadata registry.
    
    Args:
        context: Optional ServerContext. If provided, returns the context's
                metadata_registry. Otherwise, falls back to the global instance
                for backward compatibility.
    
    Returns:
        ToolMetadataRegistry instance
        
    Note:
        The global instance is deprecated. New code should use ServerContext.
        
    Example:
        >>> # New code (recommended):
        >>> with ServerContext() as ctx:
        ...     registry = get_registry(ctx)
        
        >>> # Legacy code (still works):
        >>> registry = get_registry()
    """
    # If context provided, use it (new pattern)
    if context is not None:
        return context.metadata_registry
    
    # Fallback to global for backward compatibility (deprecated)
    return _global_registry


def tool_metadata(
    runtime: str = RUNTIME_AUTO,
    requires_p2p: bool = False,
    category: str = "general",
    priority: int = 5,
    timeout_seconds: Optional[float] = 30.0,
    retry_policy: str = "none",
    memory_intensive: bool = False,
    cpu_intensive: bool = False,
    io_intensive: bool = False,
    mcp_schema: Optional[dict] = None,
    mcp_description: Optional[str] = None
) -> Callable:
    """
    Decorator to register tool metadata.
    
    This decorator automatically registers metadata for a tool function
    and attaches the metadata as attributes to the function.
    
    Args:
        runtime: Preferred runtime ("fastapi", "trio", or "auto")
        requires_p2p: Whether tool requires P2P capabilities
        category: Tool category
        priority: Execution priority (0-10)
        timeout_seconds: Maximum execution time
        retry_policy: Retry strategy
        memory_intensive: Memory usage hint
        cpu_intensive: CPU usage hint
        io_intensive: I/O usage hint
        mcp_schema: MCP schema definition
        mcp_description: Tool description
    
    Returns:
        Decorated function with metadata attached
    
    Example:
        >>> @tool_metadata(
        ...     runtime="trio",
        ...     requires_p2p=True,
        ...     category="p2p_workflow",
        ...     priority=8
        ... )
        ... async def p2p_workflow_submit(workflow: dict) -> str:
        ...     '''Submit a P2P workflow.'''
        ...     return "workflow-123"
    """
    def decorator(func: Callable) -> Callable:
        """Inner decorator that registers metadata and attaches it to *func*.

        Args:
            func: The tool function to annotate.

        Returns:
            The original *func* with ``_mcp_metadata`` and convenience
            attributes attached.
        """
        # Get function name
        tool_name = func.__name__
        
        # Get description from docstring if not provided
        description = mcp_description or inspect.getdoc(func) or f"Tool: {tool_name}"
        
        # Create metadata
        metadata = ToolMetadata(
            name=tool_name,
            runtime=runtime,
            requires_p2p=requires_p2p,
            category=category,
            priority=priority,
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
            memory_intensive=memory_intensive,
            cpu_intensive=cpu_intensive,
            io_intensive=io_intensive,
            mcp_schema=mcp_schema,
            mcp_description=description,
            _func=func
        )
        
        # Register with global registry
        get_registry().register(metadata)
        
        # Attach metadata to function
        func._mcp_metadata = metadata
        func._mcp_runtime = runtime
        func._mcp_requires_p2p = requires_p2p
        func._mcp_category = category
        func._mcp_priority = priority
        
        return func
    
    return decorator


def get_tool_metadata(func: Callable) -> Optional[ToolMetadata]:
    """
    Get metadata for a function.
    
    Args:
        func: Function to get metadata for
        
    Returns:
        ToolMetadata instance or None if not registered
    """
    if hasattr(func, '_mcp_metadata'):
        return func._mcp_metadata
    
    # Try registry lookup by name
    return get_registry().get(func.__name__)


__all__ = [
    "ToolMetadata",
    "ToolMetadataRegistry",
    "get_registry",
    "tool_metadata",
    "get_tool_metadata",
    "RUNTIME_FASTAPI",
    "RUNTIME_TRIO",
    "RUNTIME_AUTO"
]
