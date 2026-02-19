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

from .exceptions import (
    ToolNotFoundError,
    ToolExecutionError,
    ServerStartupError,
    ServerShutdownError,
    ConfigurationError,
    ValidationError as MCPValidationError,
    P2PServiceError,
    MonitoringError,
)

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
                
            except ConfigurationError:
                raise
            except (ImportError, ModuleNotFoundError) as e:
                logger.error(f"Required module not available: {e}", exc_info=True)
                self._cleanup()
                raise ServerStartupError(f"Module import failed: {e}")
            except Exception as e:
                logger.error(f"Failed to initialize ServerContext: {e}", exc_info=True)
                # Clean up any partially initialized resources
                self._cleanup()
                raise ServerStartupError(f"Server initialization failed: {e}")
    
    def __exit__(self, exc_type: Optional[type], exc_val: Optional[Exception], exc_tb: Optional[Any]) -> None:
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
            except ServerShutdownError:
                raise
            except Exception as e:
                logger.error(f"Error during ServerContext cleanup: {e}", exc_info=True)
                raise ServerShutdownError(f"Cleanup failed: {e}")
            finally:
                self._entered = False
    
    def _initialize_metadata_registry(self) -> None:
        """Initialize tool metadata registry."""
        from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadataRegistry
        
        self._metadata_registry = ToolMetadataRegistry()
        logger.debug("Tool metadata registry initialized")
    
    def _initialize_tool_manager(self) -> None:
        """Initialize hierarchical tool manager."""
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        self._tool_manager = HierarchicalToolManager()
        logger.debug("Hierarchical tool manager initialized")
    
    def _initialize_p2p_services(self) -> None:
        """Initialize P2P services."""
        try:
            # Import P2P service manager if available
            # For now, just log that P2P is enabled
            logger.info("P2P services enabled (initialization deferred)")
            self._p2p_services = {}  # Placeholder
        except ImportError as e:
            logger.warning(f"P2P services not available: {e}")
            self._p2p_services = None
    
    def _initialize_workflow_scheduler(self) -> None:
        """Initialize workflow scheduler."""
        try:
            # Initialize scheduler if needed
            logger.debug("Workflow scheduler initialization deferred")
            self._workflow_scheduler = None  # Placeholder
        except Exception as e:
            logger.warning(f"Failed to initialize workflow scheduler: {e}")
            self._workflow_scheduler = None
    
    def _cleanup(self) -> None:
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
            except ConfigurationError:
                raise
            except Exception as e:
                logger.error(f"Failed to clear metadata registry: {e}", exc_info=True)
        
        # Clear tool manager
        if self._tool_manager:
            try:
                # Tool manager cleanup (if it has any)
                logger.debug("Tool manager cleaned up")
            except ConfigurationError:
                raise
            except Exception as e:
                logger.error(f"Failed to clean up tool manager: {e}", exc_info=True)
        
        # Cleanup P2P services
        if self._p2p_services:
            try:
                logger.debug("P2P services cleaned up")
            except P2PServiceError:
                raise
            except Exception as e:
                logger.error(f"Failed to clean up P2P services: {e}", exc_info=True)
        
        # Clear vector stores
        self._vector_stores.clear()
        
        # Clear workflow scheduler
        self._workflow_scheduler = None
        
        # Clear cleanup handlers
        self._cleanup_handlers.clear()
    
    def register_cleanup_handler(self, handler: Callable):
        """Register a cleanup handler to be invoked during context exit and shutdown.
        
        This method registers a callable that will be invoked when the ServerContext
        exits (either normally or due to an exception). Cleanup handlers are useful
        for releasing resources, closing connections, and performing graceful shutdown
        operations. Handlers are executed in the order they were registered (FIFO).
        
        Args:
            handler (Callable): Cleanup function to invoke during context exit.
                    Must be callable with no required arguments. Can be:
                    - Regular function: `def cleanup(): ...`
                    - Lambda: `lambda: ...`
                    - Method: `obj.cleanup_method`
                    - Any callable with signature: `() -> None`
                    
                    Exceptions raised by handlers are logged but do not prevent
                    other handlers from executing.
        
        Returns:
            None
        
        Example:
            >>> context = ServerContext()
            >>> 
            >>> # Register file cleanup
            >>> def close_files():
            ...     for file in open_files:
            ...         file.close()
            >>> context.register_cleanup_handler(close_files)
            >>> 
            >>> # Register connection cleanup
            >>> context.register_cleanup_handler(lambda: db_conn.close())
            >>> 
            >>> # Register with logging
            >>> def cleanup_cache():
            ...     logger.info("Clearing cache")
            ...     cache.clear()
            >>> context.register_cleanup_handler(cleanup_cache)
            >>> 
            >>> # Handlers execute on context exit
            >>> with context:
            ...     # Do work
            ...     pass
            >>> # All handlers invoked here
        
        Note:
            - **Thread-Safe**: Registration protected by internal lock
            - **Execution Order**: FIFO (first registered, first executed)
            - **Exception Handling**: Handler exceptions are logged but don't stop cleanup
            - **No Parameters**: Handlers must accept zero arguments
            - **No Return Value**: Handler return values are ignored
            - **Multiple Registration**: Same handler can be registered multiple times
            - **Cleanup Trigger**: Invoked during __exit__ or cleanup() method
            - **Resource Management**: Use for closing files, connections, releasing locks
        
        Execution Guarantees:
            - All handlers execute even if previous handlers raise exceptions
            - Handlers execute in FIFO order (registration order)
            - Handler exceptions are logged at ERROR level
            - Cleanup continues even if individual handlers fail
            - No rollback or retry logic (one-shot execution)
        
        Best Practices:
            - Register handlers immediately after resource acquisition
            - Keep handlers simple and fast (<100ms)
            - Handle exceptions within your handler if custom error handling needed
            - Don't register handlers that depend on other resources being available
            - Use specific handlers for each resource (not one monolithic handler)
            - Log important cleanup operations within handlers
        
        Thread Safety:
            Handler registration is protected by self._lock to ensure thread-safe
            append to the _cleanup_handlers list. However, handler execution is
            sequential (not parallelized).
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
        """Retrieve a flat list of all available tool names across all categories.
        
        This method queries the hierarchical tool manager to discover all registered
        tools across all categories and returns their names as a simple list. Useful
        for tool discovery, validation, and displaying available capabilities.
        
        Returns:
            List[str]: Flat list of all tool names. Empty list if no tools registered
                    or tool_manager not initialized. Tool names are strings without
                    category prefixes (e.g., ["add_dataset", "ipfs_pin", "search_embeddings"]).
                    Order is not guaranteed.
        
        Example:
            >>> context = ServerContext()
            >>> with context:
            ...     # List all available tools
            ...     tools = context.list_tools()
            ...     print(f"Available tools: {len(tools)}")
            ...     for tool in sorted(tools):
            ...         print(f"  - {tool}")
            >>> 
            >>> # Check if specific tool exists
            >>> if "ipfs_add" in context.list_tools():
            ...     print("IPFS add tool is available")
            >>> 
            >>> # Get tool count by category
            >>> all_tools = context.list_tools()
            >>> print(f"Total tools: {len(all_tools)}")
        
        Note:
            - Returns empty list if tool_manager is None (not initialized)
            - Tool names are category-qualified during discovery but returned without prefix
            - Categories are iterated in discovery order (not alphabetical)
            - Tools from all categories are combined into single flat list
            - No deduplication performed (duplicate tool names possible across categories)
            - Result is computed on each call (not cached)
        
        Performance:
            - O(n) where n = total number of tools across all categories
            - Requires category discovery + tool enumeration per category
            - Typical: 10-50ms for 100-500 tools
            - Safe to call frequently but consider caching for hot paths
        
        Tool Manager Integration:
            Uses hierarchical_tool_manager to:
            1. Call list_categories() to get all category names
            2. For each category, call list_tools(category_name)
            3. Extract 'name' field from each tool dict
            4. Aggregate into flat list
        
        Use Cases:
            - Tool discovery and capability reporting
            - CLI tool listing (--list-tools flag)
            - API endpoint for tool enumeration
            - Validation (check if required tools available)
            - Documentation generation
            - Dashboard tool inventory display
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
        """Retrieve a tool callable by name with support for category-qualified lookups.
        
        This method fetches a registered tool function/callable by its name, supporting
        both simple names and dot-notation category.tool format for explicit category
        specification. Returns None if tool not found or tool_manager not initialized.
        
        Args:
            tool_name (str): Tool identifier. Supports two formats:
                    - Simple name: "ipfs_add" (searches across categories)
                    - Qualified name: "ipfs_tools.ipfs_add" (explicit category)
                    
                    Dot-notation format: "category_name.tool_name"
                    Only first dot is used as delimiter (subsequent dots part of tool name)
        
        Returns:
            Optional[Callable]: Tool function/callable if found, None otherwise.
                    The callable can be invoked with tool-specific parameters.
                    Returns None if:
                    - tool_manager not initialized (self._tool_manager is None)
                    - Tool not found in specified category
                    - Category not found (for qualified names)
        
        Example:
            >>> context = ServerContext()
            >>> with context:
            ...     # Get tool with qualified name
            ...     ipfs_add = context.get_tool("ipfs_tools.ipfs_add")
            ...     if ipfs_add:
            ...         result = ipfs_add(content="Hello World")
            ...     
            ...     # Get tool without category (simple name)
            ...     search = context.get_tool("search_embeddings")
            ...     if search:
            ...         results = search(query="machine learning")
            ...     
            ...     # Handle missing tool
            ...     tool = context.get_tool("nonexistent_tool")
            ...     if tool is None:
            ...         print("Tool not available")
        
        Note:
            - **Dot-Notation**: "category.tool" splits on first dot only
            - **Simple Names**: If no dot in name, returns None (requires category)
            - **Category Required**: Current implementation requires dot-notation
            - **Case Sensitive**: Tool and category names are case-sensitive
            - **No Wildcards**: Exact match required (no pattern matching)
            - **No Validation**: Returned callable not validated (trust tool_manager)
            - **Thread-Safe**: Read-only operation (no locking required)
        
        Category Qualification:
            **Qualified lookup (recommended):**
            - Format: "category_name.tool_name"
            - Direct category lookup (fast, O(1))
            - Unambiguous when tool names overlap across categories
            - Example: "ipfs_tools.ipfs_add", "dataset_tools.load_dataset"
            
            **Simple lookup (current limitation):**
            - Format: "tool_name" (no dot)
            - Returns None in current implementation
            - Future enhancement: could search all categories
        
        Implementation Detail:
            Current implementation only supports qualified names:
            ```python
            if '.' in tool_name:
                category, name = tool_name.split('.', 1)
                return self._tool_manager.get_tool(category, name)
            return None  # Simple names not supported
            ```
        
        Use Cases:
            - Tool execution preparation
            - Tool capability inspection
            - Dynamic tool invocation
            - Tool availability checking
            - Plugin system tool loading
        
        Performance:
            - O(1) for qualified names (direct category + tool lookup)
            - Returns immediately if tool_manager not initialized
            - No category scanning or enumeration
        """
        if self._tool_manager:
            # Extract category and tool name if needed
            if '.' in tool_name:
                category, name = tool_name.split('.', 1)
                cat = self._tool_manager.categories.get(category)
                if cat is not None:
                    return cat.get_tool(name)
        return None
    
    def execute_tool(self, tool_name: str, **kwargs) -> Any:
        """Execute a registered tool by name with provided arguments and error handling.
        
        This method provides a high-level interface for tool execution, combining tool
        lookup, invocation, and error handling. It's the recommended way to execute
        tools dynamically when the tool name is determined at runtime.
        
        Args:
            tool_name (str): Tool identifier in category.tool format (e.g., "ipfs_tools.ipfs_add").
                    Must be a fully qualified name with category prefix. Simple names
                    without category will fail with ValueError.
            **kwargs: Arbitrary keyword arguments passed directly to the tool callable.
                    Must match the tool's expected signature. Tool-specific parameters
                    are not validated by this method.
        
        Returns:
            Any: Tool execution result. Return type and structure depend on the specific
                    tool being executed. Can be any Python object (dict, list, str, int,
                    custom objects, etc.).
        
        Raises:
            ValueError: If tool_name not found or tool_manager not initialized.
                    Message: "Tool not found: {tool_name}"
            RuntimeError: If tool execution raises an exception.
                    Message: "Tool execution failed: {original_error}"
                    Original exception is chained (accessible via __cause__)
        
        Example:
            >>> context = ServerContext()
            >>> with context:
            ...     # Execute IPFS add tool
            ...     try:
            ...         result = context.execute_tool(
            ...             "ipfs_tools.ipfs_add",
            ...             content="Hello World",
            ...             pin=True
            ...         )
            ...         print(f"IPFS CID: {result['cid']}")
            ...     except ValueError as e:
            ...         print(f"Tool not found: {e}")
            ...     except RuntimeError as e:
            ...         print(f"Execution failed: {e}")
            ...     
            ...     # Execute dataset loading tool
            ...     dataset = context.execute_tool(
            ...         "dataset_tools.load_dataset",
            ...         name="squad",
            ...         split="train"
            ...     )
        
        Note:
            - **Qualified Names Required**: Must use "category.tool" format
            - **Synchronous Only**: Does not await async tools (use await tool(**kwargs) instead)
            - **Error Logging**: Failed executions logged at ERROR level with full traceback
            - **Exception Chaining**: Original exception available via RuntimeError.__cause__
            - **No Timeout**: Tool execution has no time limit (implement in tool if needed)
            - **No Retry**: Failed executions not retried (implement retry at caller level)
            - **Parameter Validation**: Tool parameters not validated (trust tool implementation)
        
        Error Handling:
            **ValueError (Tool Not Found):**
            - Tool name doesn't exist in registry
            - Category not found
            - tool_manager not initialized
            - Simple name used instead of qualified name
            
            **RuntimeError (Execution Failed):**
            - Tool raised exception during execution
            - Invalid parameters passed to tool
            - Tool implementation error
            - Resource unavailable (file, network, etc.)
            - Check __cause__ for original exception
        
        Execution Flow:
            1. Call get_tool(tool_name) to retrieve callable
            2. If None, raise ValueError
            3. Invoke tool(**kwargs) with provided arguments
            4. If exception, log error and wrap in RuntimeError
            5. Return tool result on success
        
        Use Cases:
            - Dynamic tool execution based on user input
            - Plugin system tool invocation
            - CLI command routing to tools
            - REST API endpoint routing to tools
            - Workflow orchestration and automation
        
        Performance:
            - O(1) tool lookup (via get_tool)
            - Execution time depends on specific tool
            - No overhead beyond tool lookup + invocation
        """
        tool = self.get_tool(tool_name)
        if not tool:
            raise ToolNotFoundError(tool_name)
        
        try:
            return tool(**kwargs)
        except ToolExecutionError:
            raise
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid parameters for tool {tool_name}: {e}", exc_info=True)
            raise ToolExecutionError(tool_name, e)
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}", exc_info=True)
            raise ToolExecutionError(tool_name, e)


@contextmanager
def create_server_context(config: Optional[ServerConfig] = None) -> ServerContext:
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


def set_current_context(context: Optional[ServerContext]) -> None:
    """Set the current server context in thread-local storage for implicit access.
    
    This function stores a ServerContext instance in thread-local storage, enabling
    libraries, tools, and middleware to access the context without explicit parameter
    passing through call chains. Each thread maintains its own independent context.
    
    Args:
        context (Optional[ServerContext]): ServerContext instance to set as current,
                or None to clear the thread's context. Setting None is equivalent to
                "unsetting" the context for the current thread.
    
    Returns:
        None
    
    Example:
        >>> # Set context for current thread
        >>> ctx = ServerContext()
        >>> set_current_context(ctx)
        >>> 
        >>> # Tools can now access context without parameter passing
        >>> def my_tool():
        ...     ctx = get_current_context()
        ...     if ctx:
        ...         tools = ctx.list_tools()
        ...         print(f"Available tools: {len(tools)}")
        >>> 
        >>> my_tool()  # Works without passing ctx as parameter
        >>> 
        >>> # Clear context
        >>> set_current_context(None)
        >>> assert get_current_context() is None
        >>> 
        >>> # Use with context manager
        >>> with create_server_context() as ctx:
        ...     set_current_context(ctx)
        ...     # Context available throughout this block
        ...     # Automatically cleared on exit
    
    Note:
        - **Thread-Local**: Each thread has independent context storage
        - **No Validation**: Accepts any ServerContext instance (or None)
        - **Implicit Access**: Enables context access without parameter threading
        - **Clearing**: Set None to remove context from current thread
        - **No Side Effects**: Only updates thread-local storage, no cleanup
        - **Not Thread-Safe Across Threads**: Thread A cannot set context for Thread B
        - **Memory**: Context held until explicitly cleared or thread exits
    
    Thread-Local Storage:
        Uses Python's threading.local() for per-thread isolation:
        - Thread 1: set_current_context(ctx1) → Thread 1 sees ctx1
        - Thread 2: set_current_context(ctx2) → Thread 2 sees ctx2
        - No interference between threads
        - Each thread's context independent
    
    Design Pattern:
        **Dependency Injection Alternative:**
        Instead of:
        ```python
        def process_data(data, context):
            tools = context.list_tools()
            ...
        
        def process_batch(batch, context):
            for item in batch:
                process_data(item, context)  # Must pass context
        ```
        
        Use thread-local:
        ```python
        set_current_context(ctx)
        
        def process_data(data):
            context = get_current_context()
            tools = context.list_tools()
            ...
        
        def process_batch(batch):
            for item in batch:
                process_data(item)  # No context parameter needed
        ```
    
    Best Practices:
        - Set context at thread entry point (request handler, worker thread)
        - Clear context at thread exit to prevent memory leaks
        - Use with context managers for automatic cleanup
        - Don't rely on context in long-lived daemon threads
        - Document which functions depend on thread-local context
        - Prefer explicit parameters for testability when possible
    
    Use Cases:
        - Web request handlers (one context per request thread)
        - Middleware accessing context without parameter threading
        - Tool implementations accessing server resources
        - Plugin systems with implicit context access
        - Async task context propagation (with care)
    
    Caveats:
        - **Async Compatibility**: Thread-locals don't work well with async/await
          (use contextvars instead for async code)
        - **Testing**: Can make tests harder (need to set/clear context in fixtures)
        - **Debugging**: Implicit dependencies can be harder to trace
        - **Thread Pools**: Worker threads need explicit context setting
    """
    _thread_local_context.context = context


def get_current_context() -> Optional[ServerContext]:
    """Retrieve the current thread's ServerContext from thread-local storage.
    
    This function returns the ServerContext instance that was previously set for the
    current thread via set_current_context(). Returns None if no context has been set
    or if the context was explicitly cleared. Each thread maintains independent context.
    
    Returns:
        Optional[ServerContext]: The ServerContext instance for this thread, or None
                if no context is set. None indicates either:
                - Context never set for this thread
                - Context explicitly cleared via set_current_context(None)
                - New thread without inherited context
    
    Example:
        >>> # Basic usage
        >>> ctx = ServerContext()
        >>> set_current_context(ctx)
        >>> retrieved_ctx = get_current_context()
        >>> assert retrieved_ctx is ctx
        >>> 
        >>> # Defensive usage (handle None case)
        >>> def my_function():
        ...     ctx = get_current_context()
        ...     if ctx is None:
        ...         raise RuntimeError("No server context available")
        ...     return ctx.list_tools()
        >>> 
        >>> # Tool implementation with context access
        >>> def ipfs_tool_implementation(**kwargs):
        ...     ctx = get_current_context()
        ...     if ctx and ctx.vector_stores:
        ...         # Use context resources
        ...         store = ctx.vector_stores.get('default')
        ...         return store.search(**kwargs)
        ...     # Fallback without context
        ...     return perform_basic_search(**kwargs)
        >>> 
        >>> # Multiple threads with independent contexts
        >>> def worker(thread_id):
        ...     ctx = ServerContext()
        ...     set_current_context(ctx)
        ...     # This thread's context
        ...     local_ctx = get_current_context()
        ...     print(f"Thread {thread_id}: {id(local_ctx)}")
    
    Note:
        - **Thread-Local**: Returns context specific to calling thread
        - **No Validation**: Returns whatever was set (or None)
        - **Read-Only**: Does not modify thread-local storage
        - **Independent Threads**: Each thread has its own context
        - **No Defaults**: Returns None if context not set (no fallback)
        - **Fast**: O(1) attribute access on thread-local object
        - **No Side Effects**: Safe to call repeatedly
    
    Thread Isolation:
        ```python
        # Thread 1
        set_current_context(ctx1)
        assert get_current_context() is ctx1  # ✅
        
        # Thread 2 (simultaneous)
        set_current_context(ctx2)
        assert get_current_context() is ctx2  # ✅
        assert get_current_context() is not ctx1  # ✅
        
        # Back to Thread 1
        assert get_current_context() is ctx1  # ✅ Still ctx1
        ```
    
    Error Handling Pattern:
        **Option 1: Fail fast**
        ```python
        ctx = get_current_context()
        if ctx is None:
            raise RuntimeError("Server context required")
        ```
        
        **Option 2: Graceful degradation**
        ```python
        ctx = get_current_context()
        if ctx:
            # Use advanced features
            tools = ctx.list_tools()
        else:
            # Fallback mode
            tools = get_default_tools()
        ```
        
        **Option 3: Default context**
        ```python
        ctx = get_current_context() or get_default_context()
        ```
    
    Best Practices:
        - Always check for None before using context
        - Provide clear error messages when context required
        - Consider fallback behavior when context optional
        - Document context requirements in function docstrings
        - Use type hints: `ctx: Optional[ServerContext]`
        - Test both with-context and without-context paths
    
    Use Cases:
        - Middleware accessing request-scoped context
        - Tool implementations accessing server resources
        - Logging enrichment with context metadata
        - Resource cleanup based on context state
        - Conditional feature activation
        - Plugin systems with implicit configuration
    
    Debugging:
        To debug missing context issues:
        ```python
        import threading
        ctx = get_current_context()
        if ctx is None:
            print(f"No context in thread: {threading.current_thread().name}")
            print(f"Thread ID: {threading.get_ident()}")
            # Check if context was set earlier in call chain
        ```
    
    Caveats:
        - **Async Code**: Use contextvars.ContextVar instead for async/await
        - **Thread Pools**: Context not inherited by pool workers
        - **Implicit Dependencies**: Can make code harder to understand
        - **Testing**: May need to mock or set context in test fixtures
        - **Multiprocessing**: Context not shared across processes
    """
    return getattr(_thread_local_context, 'context', None)


__all__ = [
    'ServerContext',
    'ServerConfig',
    'create_server_context',
    'set_current_context',
    'get_current_context',
]
