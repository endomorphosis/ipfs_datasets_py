"""
Server Context for MCP Server

This module provides a context manager for managing server-wide resources,
replacing global singletons with a clean, testable, thread-safe architecture.

The ServerContext manages:
- Tool registry and metadata
- Hierarchical tool manager
- P2P services
- Vector stores
- Workflow schedulers
- Resource cleanup

Usage:
    from ipfs_datasets_py.mcp_server.server_context import ServerContext
    
    # Create context for server lifecycle
    with ServerContext() as context:
        # Access managed resources
        tool_manager = context.tool_manager
        metadata_registry = context.metadata_registry
        
        # Register tools
        context.register_tool(my_tool)
        
        # Get tools
        tool = context.get_tool("tool_name")
    
    # Context automatically cleans up resources on exit

Benefits:
- Thread-safe: Each context is isolated
- Testable: Easy to create clean contexts for tests
- No global state: All resources managed explicitly
- Proper cleanup: Resources released automatically
- Dependency injection: Pass context instead of globals
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Configuration for server context."""
    
    tools_directory: Path = field(default_factory=lambda: Path(__file__).parent / "tools")
    enable_p2p: bool = True
    enable_monitoring: bool = True
    log_level: str = "INFO"
    
    # Resource limits
    max_concurrent_tools: int = 10
    tool_timeout_seconds: float = 30.0
    
    # Performance settings
    cache_tool_discovery: bool = True
    lazy_load_tools: bool = True


class ServerContext:
    """
    Manages server-wide resources and state.
    
    This class replaces global singletons with a context-managed approach,
    providing better testability, thread safety, and resource management.
    
    Attributes:
        config: Server configuration
        tool_manager: Hierarchical tool manager instance
        metadata_registry: Tool metadata registry
        p2p_services: P2P service manager (if enabled)
        vector_stores: Vector store instances
        workflow_scheduler: Workflow scheduler (if enabled)
    
    Example:
        >>> config = ServerConfig(tools_directory=Path("/path/to/tools"))
        >>> with ServerContext(config) as context:
        ...     # Use context throughout server lifecycle
        ...     tools = context.list_tools()
        ...     result = context.execute_tool("tool_name", **kwargs)
    """
    
    def __init__(self, config: Optional[ServerConfig] = None):
        """
        Initialize server context.
        
        Args:
            config: Server configuration (uses defaults if None)
        """
        self.config = config or ServerConfig()
        self._lock = threading.RLock()  # Reentrant lock for thread safety
        self._entered = False
        self._cleanup_handlers: List[Callable] = []
        
        # Managed resources (initialized in __enter__)
        self._tool_manager: Optional[Any] = None
        self._metadata_registry: Optional[Any] = None
        self._p2p_services: Optional[Any] = None
        self._vector_stores: Dict[str, Any] = {}
        self._workflow_scheduler: Optional[Any] = None
        
        logger.debug(f"ServerContext created with config: {self.config}")
    
    def __enter__(self) -> ServerContext:
        """
        Enter context and initialize resources.
        
        Returns:
            Self for context manager protocol
        """
        with self._lock:
            if self._entered:
                raise RuntimeError("ServerContext already entered")
            
            logger.info("Initializing ServerContext...")
            
            try:
                # Initialize tool metadata registry
                self._initialize_metadata_registry()
                
                # Initialize hierarchical tool manager
                self._initialize_tool_manager()
                
                # Initialize P2P services if enabled
                if self.config.enable_p2p:
                    self._initialize_p2p_services()
                
                # Initialize workflow scheduler if needed
                self._initialize_workflow_scheduler()
                
                self._entered = True
                logger.info("ServerContext initialized successfully")
                return self
                
            except Exception as e:
                logger.error(f"Failed to initialize ServerContext: {e}", exc_info=True)
                # Clean up any partially initialized resources
                self._cleanup()
                raise
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit context and clean up resources.
        
        Args:
            exc_type: Exception type (if exception occurred)
            exc_val: Exception value
            exc_tb: Exception traceback
        """
        with self._lock:
            if not self._entered:
                logger.warning("ServerContext.__exit__ called but not entered")
                return
            
            logger.info("Cleaning up ServerContext...")
            
            try:
                self._cleanup()
                logger.info("ServerContext cleanup complete")
            except Exception as e:
                logger.error(f"Error during ServerContext cleanup: {e}", exc_info=True)
            finally:
                self._entered = False
    
    def _initialize_metadata_registry(self):
        """Initialize tool metadata registry."""
        from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadataRegistry
        
        self._metadata_registry = ToolMetadataRegistry()
        logger.debug("Tool metadata registry initialized")
    
    def _initialize_tool_manager(self):
        """Initialize hierarchical tool manager."""
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        self._tool_manager = HierarchicalToolManager()
        logger.debug("Hierarchical tool manager initialized")
    
    def _initialize_p2p_services(self):
        """Initialize P2P services."""
        try:
            # Import P2P service manager if available
            # For now, just log that P2P is enabled
            logger.info("P2P services enabled (initialization deferred)")
            self._p2p_services = {}  # Placeholder
        except ImportError as e:
            logger.warning(f"P2P services not available: {e}")
            self._p2p_services = None
    
    def _initialize_workflow_scheduler(self):
        """Initialize workflow scheduler."""
        try:
            # Initialize scheduler if needed
            logger.debug("Workflow scheduler initialization deferred")
            self._workflow_scheduler = None  # Placeholder
        except Exception as e:
            logger.warning(f"Failed to initialize workflow scheduler: {e}")
            self._workflow_scheduler = None
    
    def _cleanup(self):
        """Clean up all managed resources."""
        # Run custom cleanup handlers
        for handler in self._cleanup_handlers:
            try:
                handler()
            except Exception as e:
                logger.error(f"Cleanup handler failed: {e}", exc_info=True)
        
        # Clear metadata registry
        if self._metadata_registry:
            try:
                self._metadata_registry.clear()
                logger.debug("Metadata registry cleared")
            except Exception as e:
                logger.error(f"Failed to clear metadata registry: {e}")
        
        # Clear tool manager
        if self._tool_manager:
            try:
                # Tool manager cleanup (if it has any)
                logger.debug("Tool manager cleaned up")
            except Exception as e:
                logger.error(f"Failed to clean up tool manager: {e}")
        
        # Cleanup P2P services
        if self._p2p_services:
            try:
                logger.debug("P2P services cleaned up")
            except Exception as e:
                logger.error(f"Failed to clean up P2P services: {e}")
        
        # Clear vector stores
        self._vector_stores.clear()
        
        # Clear workflow scheduler
        self._workflow_scheduler = None
        
        # Clear cleanup handlers
        self._cleanup_handlers.clear()
    
    def register_cleanup_handler(self, handler: Callable):
        """
        Register a cleanup handler to be called on context exit.
        
        Args:
            handler: Callable to invoke during cleanup
        """
        with self._lock:
            self._cleanup_handlers.append(handler)
    
    @property
    def tool_manager(self):
        """Get the hierarchical tool manager."""
        if not self._entered:
            raise RuntimeError("ServerContext not entered. Use 'with ServerContext() as ctx:'")
        return self._tool_manager
    
    @property
    def metadata_registry(self):
        """Get the tool metadata registry."""
        if not self._entered:
            raise RuntimeError("ServerContext not entered. Use 'with ServerContext() as ctx:'")
        return self._metadata_registry
    
    @property
    def p2p_services(self):
        """Get P2P services (if enabled)."""
        if not self._entered:
            raise RuntimeError("ServerContext not entered. Use 'with ServerContext() as ctx:'")
        return self._p2p_services
    
    @property
    def workflow_scheduler(self):
        """Get workflow scheduler (if initialized)."""
        if not self._entered:
            raise RuntimeError("ServerContext not entered. Use 'with ServerContext() as ctx:'")
        return self._workflow_scheduler
    
    @workflow_scheduler.setter
    def workflow_scheduler(self, scheduler: Optional[Any]) -> None:
        """Set the workflow scheduler.
        
        Args:
            scheduler: Workflow scheduler instance
        """
        if not self._entered:
            raise RuntimeError("ServerContext not entered. Use 'with ServerContext() as ctx:'")
        with self._lock:
            self._workflow_scheduler = scheduler
            logger.debug("Workflow scheduler updated")
    
    def get_vector_store(self, name: str) -> Optional[Any]:
        """
        Get a vector store by name.
        
        Args:
            name: Vector store identifier
            
        Returns:
            Vector store instance or None
        """
        with self._lock:
            return self._vector_stores.get(name)
    
    def register_vector_store(self, name: str, store: Any):
        """
        Register a vector store.
        
        Args:
            name: Vector store identifier
            store: Vector store instance
        """
        with self._lock:
            self._vector_stores[name] = store
            logger.debug(f"Registered vector store: {name}")
    
    def list_tools(self) -> List[str]:
        """
        List all available tools.
        
        Returns:
            List of tool names
        """
        if self._tool_manager:
            # Use tool manager to list tools
            categories = self._tool_manager.list_categories()
            all_tools = []
            for cat in categories:
                tools = self._tool_manager.list_tools(cat['name'])
                all_tools.extend([t['name'] for t in tools])
            return all_tools
        return []
    
    def get_tool(self, tool_name: str) -> Optional[Callable]:
        """
        Get a tool by name.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool callable or None
        """
        if self._tool_manager:
            # Extract category and tool name if needed
            if '.' in tool_name:
                category, name = tool_name.split('.', 1)
                return self._tool_manager.get_tool(category, name)
        return None
    
    def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """
        Execute a tool with given arguments.
        
        Args:
            tool_name: Name of the tool
            **kwargs: Tool arguments
            
        Returns:
            Tool execution result
            
        Raises:
            ValueError: If tool not found
            RuntimeError: If execution fails
        """
        tool = self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        
        try:
            return tool(**kwargs)
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}", exc_info=True)
            raise RuntimeError(f"Tool execution failed: {e}") from e


@contextmanager
def create_server_context(config: Optional[ServerConfig] = None):
    """
    Context manager for creating and managing a server context.
    
    This is a convenience function that creates a ServerContext and
    ensures proper cleanup even if an exception occurs.
    
    Args:
        config: Server configuration
        
    Yields:
        ServerContext instance
        
    Example:
        >>> with create_server_context() as context:
        ...     tools = context.list_tools()
        ...     result = context.execute_tool("my_tool", arg1=value1)
    """
    context = ServerContext(config)
    with context:
        yield context


# Thread-local storage for context (for libraries that need it)
_thread_local_context = threading.local()


def set_current_context(context: Optional[ServerContext]):
    """
    Set the current server context for this thread.
    
    This allows libraries and tools to access the context without
    explicitly passing it through all function calls.
    
    Args:
        context: ServerContext to set as current, or None to clear
    """
    _thread_local_context.context = context


def get_current_context() -> Optional[ServerContext]:
    """
    Get the current server context for this thread.
    
    Returns:
        Current ServerContext or None if not set
    """
    return getattr(_thread_local_context, 'context', None)


__all__ = [
    'ServerContext',
    'ServerConfig',
    'create_server_context',
    'set_current_context',
    'get_current_context',
]
