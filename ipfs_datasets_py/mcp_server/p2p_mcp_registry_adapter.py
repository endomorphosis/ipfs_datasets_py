"""Adapter that exposes mcp_server tools in the shape expected by ipfs_accelerate_py.tool_manifest.

The p2p TaskQueue service's `call_tool` handler uses `ipfs_accelerate_py.tool_manifest`
which expects an MCP-like registry exposing a `.tools` attribute.

FastMCP does not expose `.tools` directly, and IPFSDatasetsMCPServer stores tools
as a dict name -> callable. This adapter normalizes that into the expected dict:

  tools[name] = {"function": callable, "description": str, "input_schema": dict}

Enhanced for MCP++ dual-runtime support:
- Supports both FastAPI and Trio-native tools
- Adds runtime metadata to tool registration
- Enables runtime-specific tool filtering
- Maintains backward compatibility

It also forwards P2P auth validation to the host server.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

from .exceptions import (
    ToolNotFoundError,
    ToolExecutionError,
    ConfigurationError,
    P2PServiceError,
)

if TYPE_CHECKING:
    from .mcp_interfaces import MCPServerProtocol

logger = logging.getLogger(__name__)

# Runtime types for tool execution
RUNTIME_FASTAPI = "fastapi"
RUNTIME_TRIO = "trio"
RUNTIME_UNKNOWN = "unknown"

# Hierarchical tool manager meta-tools. When these are the only tools exposed by
# the host server, callers must discover and dispatch via the hierarchical system.
HIERARCHICAL_META_TOOL_NAMES: Set[str] = {
    "tools_list_categories",
    "tools_list_tools",
    "tools_get_schema",
    "tools_dispatch",
}


class P2PMCPRegistryAdapter:
    """Adapter for exposing MCP tools to P2P services with dual-runtime support.
    
    Supports both FastAPI and Trio-native tools, adding runtime metadata
    to enable efficient routing and execution in the dual-runtime architecture.
    """
    
    def __init__(
        self,
        host_server: MCPServerProtocol | Any,
        default_runtime: str = RUNTIME_FASTAPI,
        enable_runtime_detection: bool = True,
    ) -> None:
        """Initialize the P2P MCP registry adapter.
        
        Args:
            host_server: The MCP server instance (should implement MCPServerProtocol)
            default_runtime: Default runtime for tools without explicit metadata
            enable_runtime_detection: Whether to auto-detect tool runtime
        """
        self._host: MCPServerProtocol | Any = host_server
        self._default_runtime = default_runtime
        self._enable_runtime_detection = enable_runtime_detection
        
        # Cache for runtime metadata
        self._runtime_metadata: Dict[str, str] = {}
        
        # Track which tools are Trio-native
        self._trio_tools: Set[str] = set()
        self._fastapi_tools: Set[str] = set()

    @property
    def accelerate_instance(self) -> Any:
        # Used by the P2P service to pass into ctx.state.accelerate.
        return self._host

    @property
    def tools(self) -> Dict[str, Dict[str, Any]]:
        """Get all tools with runtime metadata.
        
        PHASE 2 WEEK 5: Enhanced to support hierarchical tools discovery.
        Falls back to hierarchical tool manager when flat tools unavailable.
        
        Returns dict of tool name -> tool descriptor with:
        - function: The callable
        - description: Tool description
        - input_schema: Input validation schema
        - runtime: Runtime type (fastapi/trio/unknown)
        - runtime_metadata: Additional runtime-specific metadata
        """
        out: Dict[str, Dict[str, Any]] = {}
        host_tools = getattr(self._host, "tools", None)
        
        # Phase 2 Week 5: If the host only exposes hierarchical meta-tools,
        # fall back to hierarchical discovery. Do not fall back just because
        # the registry is small (unit tests commonly register 1-3 tools).
        if not isinstance(host_tools, dict):
            return out
        if host_tools and set(host_tools.keys()).issubset(HIERARCHICAL_META_TOOL_NAMES):
            logger.debug("Using hierarchical tool discovery (meta-tools only)")
            return self._get_hierarchical_tools()

        # Legacy: Process flat tools if available (backward compatibility)
        for name, fn in host_tools.items():
            if not callable(fn):
                continue
            
            # Get tool description
            try:
                desc = fn.__doc__ or ""
            except AttributeError:
                desc = ""
            except Exception as e:
                logger.debug(f"Error getting docstring for {name}: {e}")
                desc = ""
            
            # Detect or retrieve runtime
            runtime = self._get_tool_runtime(name, fn)
            
            # Build tool descriptor with runtime metadata
            out[str(name)] = {
                "function": fn,
                "description": str(desc),
                "input_schema": {},
                "runtime": runtime,
                "runtime_metadata": {
                    "is_async": self._is_async_function(fn),
                    "is_trio_native": runtime == RUNTIME_TRIO,
                    "requires_trio_context": runtime == RUNTIME_TRIO,
                },
                # tool_manifest.tool_execution_context will treat missing
                # execution_context as unknown; the P2P service embeds a default.
            }
        
        return out
    
    def _get_tool_manager_safely(self):
        """Get hierarchical tool manager with safe import handling."""
        try:
            from .hierarchical_tool_manager import get_tool_manager
            manager = get_tool_manager()
            if manager is None:
                logger.warning("Hierarchical tool manager not available")
            return manager
        except ImportError as e:
            logger.warning(f"Hierarchical tool manager module not available: {e}")
            return None
        except ConfigurationError:
            raise
        except Exception as e:
            logger.error(f"Error getting tool manager: {e}", exc_info=True)
            return None
    
    def _discover_categories(self, manager):
        """Discover all available categories from the tool manager."""
        from ipfs_datasets_py.utils.anyio_compat import run as _anyio_run, in_async_context

        # Cannot call from inside a running async context
        if in_async_context():
            logger.debug("Cannot discover hierarchical tools in running async context")
            return []

        # Run async list_categories
        categories_result = _anyio_run(manager.list_categories())
        
        # Extract category names from result
        if isinstance(categories_result, dict) and "categories" in categories_result:
            category_list = categories_result["categories"]
            categories = [cat.get("name") or cat.get("category") for cat in category_list if isinstance(cat, dict)]
        else:
            categories = []
        
        logger.debug(f"Discovering tools from {len(categories)} categories")
        return categories
    
    def _build_tool_wrapper(self, category: str, tool_name: str, description: str = ""):
        """Build a callable wrapper for tool dispatch."""
        def make_tool_wrapper(cat, name):
            async def wrapper(**kwargs):
                from .hierarchical_tool_manager import tools_dispatch
                return await tools_dispatch(
                    category=cat,
                    tool_name=name,
                    **kwargs
                )
            wrapper.__name__ = name
            wrapper.__doc__ = description
            return wrapper
        
        return make_tool_wrapper(category, tool_name)
    
    def _process_category_tools(self, manager, category: str, out: Dict[str, Dict[str, Any]]):
        """Process all tools in a given category and add to output dict."""
        from ipfs_datasets_py.utils.anyio_compat import run as _anyio_run

        try:
            # Get tools in this category (async operation)
            cat_tools_result = _anyio_run(manager.list_tools(category))
            
            # Extract tools list
            if isinstance(cat_tools_result, dict) and "tools" in cat_tools_result:
                cat_tools = cat_tools_result["tools"]
            else:
                return
            
            for tool_info in cat_tools:
                tool_name = tool_info.get("name")
                if not tool_name:
                    continue
                
                try:
                    # Create wrapper function
                    fn = self._build_tool_wrapper(
                        category, 
                        tool_name, 
                        tool_info.get("description", "")
                    )
                    
                    # Build tool descriptor
                    out[str(tool_name)] = {
                        "function": fn,
                        "description": tool_info.get("description", ""),
                        "input_schema": tool_info.get("input_schema", {}),
                        "runtime": self._default_runtime,
                        "runtime_metadata": {
                            "is_async": True,
                            "is_trio_native": False,
                            "requires_trio_context": False,
                            "category": category,
                            "hierarchical": True,
                        },
                    }
                except ToolExecutionError:
                    raise
                except (TypeError, ValueError) as e:
                    logger.warning(f"Invalid tool configuration for {tool_name}: {e}")
                except Exception as e:
                    logger.debug(f"Error creating wrapper for {tool_name}: {e}")
                    
        except ConfigurationError:
            raise
        except (ImportError, ModuleNotFoundError) as e:
            logger.warning(f"Failed to import tools from category {category}: {e}")
        except Exception as e:
            logger.debug(f"Error processing category {category}: {e}")
    
    def _get_hierarchical_tools(self) -> Dict[str, Dict[str, Any]]:
        """Get all tools from hierarchical tool manager.
        
        Phase 2 Week 5: New method to discover tools through hierarchical system
        instead of flat registration. This eliminates the 99% overhead from
        duplicate registrations.
        
        Returns:
            Dict of tool name -> tool descriptor for all discovered tools
        """
        out: Dict[str, Dict[str, Any]] = {}
        
        try:
            # Get tool manager safely
            manager = self._get_tool_manager_safely()
            if manager is None:
                return out
            
            # Discover all categories
            try:
                categories = self._discover_categories(manager)
                
                # Process each category
                for category in categories:
                    self._process_category_tools(manager, category, out)
                
                logger.info(f"Discovered {len(out)} tools through hierarchical system")
                
            except ConfigurationError:
                raise
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Module import failed during discovery: {e}")
            except Exception as e:
                logger.debug(f"Error getting categories: {e}")
            
        except ConfigurationError:
            raise
        except P2PServiceError:
            raise
        except Exception as e:
            logger.error(f"Error discovering hierarchical tools: {e}", exc_info=True)
            import traceback
            logger.debug(traceback.format_exc())
        
        return out
    
    def _get_tool_runtime(self, name: str, fn: Any) -> str:
        """Determine the runtime for a tool.
        
        Args:
            name: Tool name
            fn: Tool function
            
        Returns:
            Runtime type (fastapi/trio/unknown)
        """
        # Check cache first
        if name in self._runtime_metadata:
            return self._runtime_metadata[name]
        
        runtime = RUNTIME_UNKNOWN
        
        # Check explicit tracking
        if name in self._trio_tools:
            runtime = RUNTIME_TRIO
        elif name in self._fastapi_tools:
            runtime = RUNTIME_FASTAPI
        elif self._enable_runtime_detection:
            # Auto-detect based on function attributes
            runtime = self._detect_runtime(fn)
        else:
            runtime = self._default_runtime
        
        # Cache the result
        self._runtime_metadata[name] = runtime
        return runtime
    
    def _detect_runtime(self, fn: Any) -> str:
        """Auto-detect runtime based on function attributes.
        
        Args:
            fn: Tool function
            
        Returns:
            Detected runtime type
        """
        # Check for explicit runtime marker
        runtime_marker = getattr(fn, "_mcp_runtime", None)
        if runtime_marker in (RUNTIME_FASTAPI, RUNTIME_TRIO):
            return runtime_marker
        
        # Check module path for hints
        try:
            module = getattr(fn, "__module__", "")
            if "trio" in module.lower() or "mcplusplus" in module.lower():
                return RUNTIME_TRIO
        except AttributeError:
            pass
        except Exception as e:
            logger.debug(f"Error detecting runtime from module: {e}")
            pass
        
        # Default to FastAPI
        return RUNTIME_FASTAPI
    
    def _is_async_function(self, fn: Any) -> bool:
        """Check if function is async.
        
        Args:
            fn: Function to check
            
        Returns:
            True if async function
        """
        import inspect
        try:
            return inspect.iscoroutinefunction(fn)
        except (TypeError, AttributeError):
            return False
        except Exception as e:
            logger.debug(f"Error checking if function is async: {e}")
            return False

    async def validate_p2p_message(self, msg: dict) -> bool:
        fn = getattr(self._host, "validate_p2p_message", None)
        if not callable(fn):
            return False
        res = fn(msg)
        if hasattr(res, "__await__"):
            return bool(await res)
        return bool(res)
    
    # Runtime management methods
    
    def register_trio_tool(self, name: str) -> None:
        """Register a tool as Trio-native.
        
        Args:
            name: Tool name to mark as Trio-native
        """
        self._trio_tools.add(name)
        self._runtime_metadata[name] = RUNTIME_TRIO
        if name in self._fastapi_tools:
            self._fastapi_tools.remove(name)
        logger.debug(f"Registered Trio-native tool: {name}")
    
    def register_fastapi_tool(self, name: str) -> None:
        """Register a tool as FastAPI-based.
        
        Args:
            name: Tool name to mark as FastAPI-based
        """
        self._fastapi_tools.add(name)
        self._runtime_metadata[name] = RUNTIME_FASTAPI
        if name in self._trio_tools:
            self._trio_tools.remove(name)
        logger.debug(f"Registered FastAPI tool: {name}")
    
    def get_tools_by_runtime(self, runtime: str) -> Dict[str, Dict[str, Any]]:
        """Get tools filtered by runtime type.
        
        Args:
            runtime: Runtime type to filter by (fastapi/trio)
            
        Returns:
            Dict of tools matching the runtime
        """
        all_tools = self.tools
        return {
            name: descriptor
            for name, descriptor in all_tools.items()
            if descriptor.get("runtime") == runtime
        }
    
    def get_trio_tools(self) -> Dict[str, Dict[str, Any]]:
        """Get all Trio-native tools.
        
        Returns:
            Dict of Trio-native tools
        """
        return self.get_tools_by_runtime(RUNTIME_TRIO)
    
    def get_fastapi_tools(self) -> Dict[str, Dict[str, Any]]:
        """Get all FastAPI tools.
        
        Returns:
            Dict of FastAPI tools
        """
        return self.get_tools_by_runtime(RUNTIME_FASTAPI)
    
    def get_runtime_stats(self) -> Dict[str, Any]:
        """Get statistics about tool runtimes.
        
        Returns:
            Dict with runtime statistics
        """
        all_tools = self.tools
        trio_count = sum(1 for t in all_tools.values() if t.get("runtime") == RUNTIME_TRIO)
        fastapi_count = sum(1 for t in all_tools.values() if t.get("runtime") == RUNTIME_FASTAPI)
        unknown_count = sum(1 for t in all_tools.values() if t.get("runtime") == RUNTIME_UNKNOWN)
        
        return {
            "total_tools": len(all_tools),
            "trio_tools": trio_count,
            "fastapi_tools": fastapi_count,
            "unknown_tools": unknown_count,
            "runtime_detection_enabled": self._enable_runtime_detection,
            "default_runtime": self._default_runtime,
        }
    
    def is_trio_tool(self, name: str) -> bool:
        """Check if a tool is Trio-native.
        
        Args:
            name: Tool name
            
        Returns:
            True if tool is Trio-native
        """
        return name in self._trio_tools or self._runtime_metadata.get(name) == RUNTIME_TRIO
    
    def clear_runtime_cache(self) -> None:
        """Clear the runtime metadata cache.
        
        Useful for testing or when tool registrations change.
        """
        self._runtime_metadata.clear()
        logger.debug("Runtime metadata cache cleared")
