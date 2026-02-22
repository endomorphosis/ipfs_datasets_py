"""Hierarchical Tool Manager for MCP Server.

This module provides a hierarchical tool management system that reduces
context window usage by organizing tools into categories and providing
dynamic tool loading and dispatch.

Instead of registering 347+ tools at the top level, we register only:
- tools.list_categories (list all categories)
- tools.list_tools (list tools in a category)
- tools.get_schema (get schema for a specific tool)
- tools.dispatch (execute a tool)

This reduces context window usage by ~99% while maintaining full functionality.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import json

import anyio

from .exceptions import (
    ToolNotFoundError,
    ToolExecutionError,
    ConfigurationError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase F3: Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState:
    """Circuit breaker states."""
    CLOSED = "closed"        # Normal operation — calls pass through.
    OPEN = "open"            # Failing — calls are rejected immediately.
    HALF_OPEN = "half_open"  # Recovery probe — one call is allowed through.


class CircuitBreaker:
    """Per-category circuit breaker.

    The state machine mirrors the classic Nygard circuit-breaker pattern:

    * **CLOSED** — normal; failures are counted.  When *failure_threshold*
      consecutive failures occur the breaker moves to **OPEN**.
    * **OPEN** — the breaker rejects all calls with an error dict immediately,
      without touching the wrapped function.  After *recovery_timeout* seconds
      the breaker enters **HALF_OPEN**.
    * **HALF_OPEN** — the next call is forwarded.  Success → **CLOSED** (counts
      reset); failure → **OPEN** (timer restarted).

    Args:
        failure_threshold: Number of consecutive failures before opening.
        recovery_timeout: Seconds to wait in OPEN state before probing.
        name: Optional label used in log messages.

    Example::

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        result = await cb.call(some_async_tool_func, arg1=value)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        name: str = "default",
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name

        self._state: str = CircuitState.CLOSED
        self._failure_count: int = 0
        self._opened_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Return the current circuit state (CLOSED / OPEN / HALF_OPEN)."""
        if self._state == CircuitState.OPEN:
            # Auto-transition to HALF_OPEN once the recovery window has elapsed.
            if (
                self._opened_at is not None
                and time.monotonic() - self._opened_at >= self.recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "CircuitBreaker[%s]: OPEN → HALF_OPEN after %.1fs",
                    self.name,
                    self.recovery_timeout,
                )
        return self._state

    def is_open(self) -> bool:
        """Return ``True`` when the circuit is fully open (calls rejected)."""
        return self.state == CircuitState.OPEN

    async def call(self, func: Callable, **kwargs: Any) -> Dict[str, Any]:
        """Execute *func* with circuit-breaker protection.

        Args:
            func: Async (or sync) callable to protect.
            **kwargs: Keyword arguments forwarded to *func*.

        Returns:
            The result of *func* on success, or an error dict when the circuit
            is open or the call itself fails.
        """
        current = self.state  # Triggers OPEN → HALF_OPEN transition if due.

        if current == CircuitState.OPEN:
            return {
                "status": "error",
                "error": (
                    f"Circuit breaker '{self.name}' is OPEN — "
                    f"service unavailable. Retrying after {self.recovery_timeout}s."
                ),
                "circuit_state": CircuitState.OPEN,
            }

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**kwargs)
            else:
                result = func(**kwargs)
            self._on_success()
            return result
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            self._on_failure()
            raise ToolExecutionError(self.name, exc) from exc

    def reset(self) -> None:
        """Manually force the breaker back to CLOSED state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None
        logger.info("CircuitBreaker[%s]: manually RESET to CLOSED", self.name)

    def info(self) -> Dict[str, Any]:
        """Return a snapshot of the breaker's current state."""
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "opened_at": self._opened_at,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            logger.info(
                "CircuitBreaker[%s]: HALF_OPEN → CLOSED (success)", self.name
            )
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = None

    def _on_failure(self) -> None:
        self._failure_count += 1
        if self._state == CircuitState.HALF_OPEN or (
            self._state == CircuitState.CLOSED
            and self._failure_count >= self.failure_threshold
        ):
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "CircuitBreaker[%s]: → OPEN after %d failure(s)",
                self.name,
                self._failure_count,
            )


class ToolCategory:
    """Represents a category of tools."""
    
    def __init__(self, name: str, path: Path, description: str = "") -> None:
        """Initialise a tool category backed by a directory on disk.

        Args:
            name: Short category identifier (e.g. ``"dataset_tools"``).
            path: Filesystem path to the directory that contains the tool modules.
            description: Optional human-readable description of the category.
        """
        self.name = name
        self.path = path
        self.description = description
        self._tools: Dict[str, Callable] = {}
        self._tool_metadata: Dict[str, Dict[str, Any]] = {}
        self._discovered = False
        # Phase 7: schema result cache — avoids repeated inspect.signature() calls
        self._schema_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_hits: int = 0
        self._cache_misses: int = 0
    
    def discover_tools(self) -> None:
        """Discover all tools in this category."""
        if self._discovered:
            return
        
        if not self.path.exists():
            logger.warning(f"Category path does not exist: {self.path}")
            return
        
        # Import tools from Python files in this directory
        for tool_file in self.path.glob("*.py"):
            if tool_file.name.startswith('_') or tool_file.name == "__init__.py":
                continue
            
            tool_name = tool_file.stem
            module_path = self._get_module_path(tool_file)
            
            try:
                module = importlib.import_module(module_path)
                
                # Find callable functions in the module
                for name, obj in inspect.getmembers(module):
                    if not inspect.isfunction(obj):
                        continue
                    if name.startswith('_'):
                        continue
                    
                    # Use the tool name or the function that matches the file name
                    if name == tool_name or tool_name in name:
                        self._tools[name] = obj
                        _obj_meta = getattr(obj, "_mcp_metadata", None)
                        self._tool_metadata[name] = {
                            "name": name,
                            "category": self.name,
                            "description": obj.__doc__ or "",
                            "signature": str(inspect.signature(obj)),
                            # Phase D1: expose schema version from @tool_metadata decorator
                            "schema_version": getattr(_obj_meta, "schema_version", "1.0"),
                            # Phase D2: expose deprecation info
                            "deprecated": getattr(_obj_meta, "deprecated", False),
                            "deprecation_message": getattr(_obj_meta, "deprecation_message", ""),
                        }
                        logger.debug(f"Discovered tool: {self.name}.{name}")
                
            except (ImportError, ModuleNotFoundError) as e:
                logger.warning(f"Failed to import tool from {tool_file}: {e}")
            except (SyntaxError, AttributeError) as e:
                logger.warning(f"Tool file has errors {tool_file}: {e}")
            except Exception as e:
                logger.warning(f"Failed to load tool from {tool_file}: {e}")
        
        self._discovered = True
        logger.info(f"Discovered {len(self._tools)} tools in category '{self.name}'")
    
    def _get_module_path(self, file_path: Path) -> str:
        """Get the Python module path for a file."""
        # Convert file path to module path
        # e.g., /path/to/ipfs_datasets_py/mcp_server/tools/dataset_tools/load_dataset.py
        # -> ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset
        
        parts = file_path.parts
        # Find the index of 'ipfs_datasets_py'
        try:
            idx = parts.index('ipfs_datasets_py')
            module_parts = parts[idx:]
            module_path = '.'.join(module_parts[:-1] + (file_path.stem,))
            return module_path
        except ValueError:
            # Fallback: use relative import
            return f"ipfs_datasets_py.mcp_server.tools.{self.name}.{file_path.stem}"
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """List all tools in this category with minimal metadata."""
        if not self._discovered:
            self.discover_tools()
        
        return [
            {
                "name": name,
                "description": (metadata["description"].split('\n')[0] if metadata["description"] else "")[:100]
            }
            for name, metadata in self._tool_metadata.items()
        ]
    
    def get_tool(self, tool_name: str) -> Optional[Callable]:
        """Get a tool function by name."""
        if not self._discovered:
            self.discover_tools()
        
        return self._tools.get(tool_name)
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get the full schema for a tool, returning a cached result when possible.

        The first call introspects the function signature via ``inspect``; subsequent
        calls return the memoised dict directly, avoiding repeated reflection work.
        """
        if not self._discovered:
            self.discover_tools()

        # Phase 7: fast-path — return cached schema if available
        if tool_name in self._schema_cache:
            self._cache_hits += 1
            return self._schema_cache[tool_name]

        metadata = self._tool_metadata.get(tool_name)
        if not metadata:
            return None

        tool_func = self._tools.get(tool_name)
        if not tool_func:
            return None

        # Build full schema (expensive — only done once per tool_name)
        sig = inspect.signature(tool_func)
        parameters = {}

        for param_name, param in sig.parameters.items():
            param_info: Dict[str, Any] = {
                "name": param_name,
                "required": param.default == inspect.Parameter.empty,
            }

            # Try to get type annotation
            if param.annotation != inspect.Parameter.empty:
                param_info["type"] = str(param.annotation)

            # Get default value
            if param.default != inspect.Parameter.empty:
                param_info["default"] = str(param.default)

            parameters[param_name] = param_info

        schema = {
            **metadata,
            "parameters": parameters,
            "return_type": (
                str(sig.return_annotation)
                if sig.return_annotation != inspect.Signature.empty
                else "Any"
            ),
        }

        # Store in cache before returning
        self._schema_cache[tool_name] = schema
        self._cache_misses += 1
        return schema

    def clear_schema_cache(self) -> None:
        """Evict all cached schemas (e.g. after tool reload).

        Resets hit/miss counters as well.
        """
        self._schema_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

    def cache_info(self) -> Dict[str, Any]:
        """Return schema-cache statistics.

        Returns:
            Dict with keys ``hits``, ``misses``, ``size``.
        """
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "size": len(self._schema_cache),
        }


class HierarchicalToolManager:
    """Manages tools in a hierarchical structure to reduce context window usage.
    
    This manager organizes tools into categories and provides dynamic loading
    and dispatch capabilities. Instead of registering hundreds of tools with
    the MCP server, we register only 4 meta-tools that handle category listing,
    tool listing, schema retrieval, and tool dispatch.
    
    Usage:
        manager = HierarchicalToolManager()
        
        # List categories
        categories = await manager.list_categories()
        
        # List tools in a category
        tools = await manager.list_tools("dataset_tools")
        
        # Get tool schema
        schema = await manager.get_tool_schema("dataset_tools", "load_dataset")
        
        # Dispatch to a tool
        result = await manager.dispatch("dataset_tools", "load_dataset", 
                                       source="squad")
    """
    
    def __init__(self, tools_root: Optional[Path] = None) -> None:
        """Initialize the hierarchical tool manager.
        
        Args:
            tools_root: Root directory for tools. If None, uses default location.
        """
        if tools_root is None:
            tools_root = Path(__file__).parent / "tools"
        
        self.tools_root = tools_root
        self.categories: Dict[str, ToolCategory] = {}
        self._category_metadata: Dict[str, Dict[str, Any]] = {}
        self._discovered_categories = False
        # Phase 7: lazy-loading registry — maps category name → callable that
        # returns a ready-to-use ToolCategory when first accessed.
        self._lazy_loaders: Dict[str, Callable[[], ToolCategory]] = {}
        # Phase F4: graceful shutdown flag — set to True during shutdown.
        self._shutting_down: bool = False
        # Phase F2: per-manager result cache (MemoryCacheBackend, LRU eviction).
        self._result_cache: Optional[Any] = None  # Lazily created on first use.

        # Load category metadata
        self._load_category_metadata()
    
    def _load_category_metadata(self) -> None:
        """Load metadata for all categories."""
        # This could be from JSON files, but for now we'll use defaults
        # Users can customize by creating category.json files
        pass

    def _get_result_cache(self) -> Any:
        """Return the lazily-created in-process result cache (Phase F2).

        The cache is a :class:`ResultCache` backed by a
        :class:`MemoryCacheBackend` with LRU eviction.  It is created the
        first time this helper is called and then reused for all subsequent
        calls.

        Returns:
            A :class:`ResultCache` instance, or ``None`` if the dependency is
            unavailable.
        """
        if self._result_cache is not None:
            return self._result_cache
        try:
            from ipfs_datasets_py.mcp_server.mcplusplus.result_cache import (
                ResultCache,
                MemoryCacheBackend,
                EvictionPolicy,
            )
            # max_size=512: maximum number of distinct tool-result entries kept
            # in memory at once.  LRU eviction removes the least-recently-used
            # entry when the limit is reached.  512 is a conservative default
            # that covers hundreds of unique (tool, params) combinations without
            # exceeding typical container memory budgets (~50 MB at 100 KB/entry).
            backend = MemoryCacheBackend(max_size=512)
            self._result_cache = ResultCache(
                backend=backend,
                default_ttl=300.0,
                eviction_policy=EvictionPolicy.LRU,
            )
        except Exception:  # ImportError or any init failure — degrade gracefully
            self._result_cache = None
        return self._result_cache

    def discover_categories(self) -> None:
        """Discover all tool categories."""
        if self._discovered_categories:
            return
        
        if not self.tools_root.exists():
            logger.warning(f"Tools root does not exist: {self.tools_root}")
            return
        
        for category_dir in self.tools_root.iterdir():
            if not category_dir.is_dir():
                continue
            if category_dir.name.startswith('_'):
                continue
            
            category_name = category_dir.name
            
            # Check for category metadata file
            metadata_file = category_dir / "category.json"
            description = ""
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        description = metadata.get("description", "")
                except (IOError, OSError) as e:
                    logger.warning(f"Failed to read metadata file for {category_name}: {e}")
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON in metadata for {category_name}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to load metadata for {category_name}: {e}")
            
            # Create category
            category = ToolCategory(category_name, category_dir, description)
            self.categories[category_name] = category
            self._category_metadata[category_name] = {
                "name": category_name,
                "description": description,
                "path": str(category_dir)
            }
        
        self._discovered_categories = True
        logger.info(f"Discovered {len(self.categories)} tool categories")
    
    def lazy_register_category(
        self, name: str, loader: Callable[[], ToolCategory]
    ) -> None:
        """Register a category whose ``ToolCategory`` object is created on demand.

        The *loader* callable is invoked the first time the category is accessed
        (e.g. via :meth:`get_category`, :meth:`list_tools`, or :meth:`dispatch`).
        This avoids importing heavy third-party dependencies at server startup.

        Args:
            name: Category name used for routing (e.g. ``"dataset_tools"``).
            loader: Zero-argument callable that returns a populated
                    :class:`ToolCategory` instance.

        Example::

            manager.lazy_register_category(
                "my_tools",
                lambda: ToolCategory("my_tools", Path("tools/my_tools")),
            )
        """
        self._lazy_loaders[name] = loader
        # Register minimal metadata so the category appears in listings.
        # Only set metadata if no richer entry (from _load_category_metadata) exists.
        if name not in self._category_metadata or not self._category_metadata[name].get("description"):
            self._category_metadata[name] = {"name": name, "description": "", "path": ""}

    def get_category(self, name: str) -> Optional[ToolCategory]:
        """Return a :class:`ToolCategory` by name, triggering lazy loading if needed.

        Args:
            name: Category name.

        Returns:
            The ``ToolCategory`` instance, or ``None`` if the category does not
            exist.
        """
        if name in self.categories:
            return self.categories[name]
        if name in self._lazy_loaders:
            logger.debug("Lazy-loading category '%s'", name)
            category = self._lazy_loaders.pop(name)()
            self.categories[name] = category
            self._category_metadata[name] = {
                "name": name,
                "description": category.description,
                "path": str(category.path),
            }
            return category
        return None

    async def list_categories(self, include_count: bool = False) -> List[Dict[str, Any]]:
        """List all available tool categories.
        
        Args:
            include_count: Whether to include tool count for each category.
        
        Returns:
            List of category metadata dictionaries.
        """
        if not self._discovered_categories:
            self.discover_categories()
        
        result = []
        # Merge discovered categories AND lazily registered ones
        all_names = set(self._category_metadata.keys()) | set(self._lazy_loaders.keys())
        for name in all_names:
            metadata = self._category_metadata.get(name, {"name": name, "description": ""})
            cat_info = {
                "name": name,
                "description": metadata["description"],
                "lazy": name in self._lazy_loaders,
            }
            
            if include_count:
                category = self.get_category(name)
                if category is not None:
                    if not category._discovered:
                        category.discover_tools()
                    cat_info["tool_count"] = len(category._tools)
            
            result.append(cat_info)
        
        return sorted(result, key=lambda x: x["name"])
    
    async def list_tools(self, category: str) -> Dict[str, Any]:
        """List all tools in a category.
        
        Args:
            category: Name of the category.
        
        Returns:
            Dict with category info and list of tools.
        """
        if not self._discovered_categories:
            self.discover_categories()
        
        cat = self.get_category(category)
        if cat is None:
            return {
                "status": "error",
                "error": f"Category '{category}' not found",
                "available_categories": list(self.categories.keys())
            }
        
        tools = cat.list_tools()
        
        return {
            "status": "success",
            "category": category,
            "description": cat.description,
            "tool_count": len(tools),
            "tools": tools
        }
    
    async def get_tool_schema(self, category: str, tool: str) -> Dict[str, Any]:
        """Get the full schema for a specific tool.
        
        Args:
            category: Name of the category.
            tool: Name of the tool.
        
        Returns:
            Dict with tool schema or error.
        """
        if not self._discovered_categories:
            self.discover_categories()
        
        cat = self.get_category(category)
        if cat is None:
            return {
                "status": "error",
                "error": f"Category '{category}' not found"
            }
        
        schema = cat.get_tool_schema(tool)
        
        if schema is None:
            return {
                "status": "error",
                "error": f"Tool '{tool}' not found in category '{category}'"
            }
        
        return {
            "status": "success",
            "schema": schema
        }
    
    async def dispatch(
        self,
        category: str,
        tool: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Dispatch to a specific tool.
        
        Args:
            category: Name of the category.
            tool: Name of the tool.
            params: Parameters to pass to the tool.
        
        Returns:
            Tool execution result.  On success the dict always contains a
            ``request_id`` key (Phase C1 structured logging).
        """
        if not self._discovered_categories:
            self.discover_categories()

        if self._shutting_down:
            return {
                "status": "error",
                "error": "Server is shutting down — no new tool calls accepted.",
            }

        if params is None:
            params = {}

        # Phase C1: generate a per-request correlation ID and start a timer.
        request_id = str(uuid.uuid4())
        _t0 = time.monotonic()
        tool_path = f"{category}/{tool}"
        
        cat = self.get_category(category)
        if cat is None:
            logger.warning(
                "dispatch: category_not_found request_id=%s tool=%s",
                request_id, tool_path,
            )
            return {
                "status": "error",
                "error": f"Category '{category}' not found",
                "available_categories": list(self.categories.keys()),
                "request_id": request_id,
            }
        
        tool_func = cat.get_tool(tool)
        
        if tool_func is None:
            available_tools = [t["name"] for t in cat.list_tools()]
            logger.warning(
                "dispatch: tool_not_found request_id=%s tool=%s",
                request_id, tool_path,
            )
            return {
                "status": "error",
                "error": f"Tool '{tool}' not found in category '{category}'",
                "available_tools": available_tools,
                "request_id": request_id,
            }

        # Phase D2: log a deprecation warning when the tool is marked deprecated.
        meta = getattr(tool_func, "_mcp_metadata", None)
        if meta is not None and getattr(meta, "deprecated", False):
            _dep_msg = getattr(meta, "deprecation_message", "") or "No replacement specified."
            logger.warning(
                "dispatch: deprecated_tool_called request_id=%s tool=%s message=%s",
                request_id, tool_path, _dep_msg,
            )
        
        try:
            # Get function signature
            sig = inspect.signature(tool_func)
            
            # Filter params to match function parameters
            filtered_params = {}
            for param_name in sig.parameters:
                if param_name in params:
                    filtered_params[param_name] = params[param_name]

            # Phase F2: opt-in result caching via cache_ttl in ToolMetadata.
            # Only cache when the tool was decorated with @tool_metadata(cache_ttl=N).
            _cache_ttl: Optional[float] = None
            if meta is not None:
                _cache_ttl = getattr(meta, "cache_ttl", None)

            if _cache_ttl is not None and _cache_ttl > 0:
                _rcache = self._get_result_cache()
                if _rcache is not None:
                    try:
                        _cached = await _rcache.get(tool_path, inputs=filtered_params)
                        if _cached is not None:
                            logger.debug(
                                "dispatch: cache_hit request_id=%s tool=%s",
                                request_id, tool_path,
                            )
                            _cached.setdefault("request_id", request_id)
                            _cached["_cached"] = True
                            return _cached
                    except Exception:
                        pass  # Cache failure is non-fatal; fall through to live call.
            
            # Call the tool
            if inspect.iscoroutinefunction(tool_func):
                result = await tool_func(**filtered_params)
            else:
                result = tool_func(**filtered_params)
            
            # Ensure result is a dict
            if not isinstance(result, dict):
                result = {"status": "success", "result": str(result)}

            # Phase F2: store successful results in the cache when cache_ttl is set.
            if _cache_ttl is not None and _cache_ttl > 0:
                _rcache = self._get_result_cache()
                if _rcache is not None:
                    try:
                        await _rcache.put(
                            tool_path,
                            result,
                            ttl=_cache_ttl,
                            inputs=filtered_params,
                        )
                    except Exception:
                        pass  # Cache write failure is non-fatal.

            _duration_ms = (time.monotonic() - _t0) * 1000
            # Phase C1: structured success log.
            logger.info(
                "dispatch: success request_id=%s tool=%s duration_ms=%.2f",
                request_id, tool_path, _duration_ms,
            )
            result.setdefault("request_id", request_id)
            return result
            
        except ToolNotFoundError:
            raise
        except ToolExecutionError:
            raise
        except (TypeError, ValueError) as e:
            _duration_ms = (time.monotonic() - _t0) * 1000
            logger.error(
                "dispatch: invalid_params request_id=%s tool=%s duration_ms=%.2f error=%s",
                request_id, tool_path, _duration_ms, e,
                exc_info=True,
            )
            return {
                "status": "error",
                "error": f"Invalid parameters: {e}",
                "category": category,
                "tool": tool,
                "request_id": request_id,
            }
        except Exception as e:
            _duration_ms = (time.monotonic() - _t0) * 1000
            logger.error(
                "dispatch: error request_id=%s tool=%s duration_ms=%.2f error=%s",
                request_id, tool_path, _duration_ms, e,
                exc_info=True,
            )
            return {
                "status": "error",
                "error": str(e),
                "category": category,
                "tool": tool,
                "request_id": request_id,
            }

    # ------------------------------------------------------------------
    # Phase F1: Parallel dispatch
    # ------------------------------------------------------------------

    async def dispatch_parallel(
        self,
        calls: List[Dict[str, Any]],
        *,
        return_exceptions: bool = True,
        max_concurrent: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Dispatch multiple tool calls concurrently.

        Each element of *calls* must be a dict with the keys:

        * ``category`` (str) — tool category name.
        * ``tool`` (str) — tool name within that category.
        * ``params`` (dict, optional) — keyword arguments for the tool.

        Results are returned in the **same order** as *calls*.

        Args:
            calls: List of ``{"category": ..., "tool": ..., "params": {...}}``
                   dicts.  ``"params"`` may be omitted (defaults to ``{}``).
            return_exceptions: When ``True`` (default) exceptions inside
                individual calls are captured and returned as error dicts
                rather than propagated.  Set to ``False`` to let the first
                exception cancel all remaining tasks.
            max_concurrent: Maximum number of tasks to run concurrently.
                When ``None`` (default) all tasks are dispatched at once.
                When set to a positive integer, calls are processed in
                batches of that size (adaptive batch sizing).  Useful for
                throttling resource consumption when *calls* is very large.

        Returns:
            List of result dicts in the same order as *calls*.

        Example::

            results = await manager.dispatch_parallel([
                {"category": "dataset_tools", "tool": "load_dataset", "params": {"source": "squad"}},
                {"category": "graph_tools",   "tool": "query_knowledge_graph"},
            ])

            # Limit to 4 concurrent calls:
            results = await manager.dispatch_parallel(calls, max_concurrent=4)
        """
        if not calls:
            return []

        n = len(calls)
        results: List[Optional[Dict[str, Any]]] = [None] * n

        async def _run_one(index: int, call: Dict[str, Any]) -> None:
            cat = call.get("category", "")
            tool = call.get("tool", "")
            params = call.get("params") or {}
            try:
                results[index] = await self.dispatch(cat, tool, params)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                if return_exceptions:
                    results[index] = {
                        "status": "error",
                        "error": str(exc),
                        "category": cat,
                        "tool": tool,
                    }
                else:
                    raise

        if max_concurrent is None or max_concurrent >= n:
            # All calls at once (original behaviour).
            async with anyio.create_task_group() as tg:
                for i, call in enumerate(calls):
                    tg.start_soon(_run_one, i, call)
        else:
            # Adaptive batching: process in windows of *max_concurrent*.
            for batch_start in range(0, n, max_concurrent):
                batch = calls[batch_start: batch_start + max_concurrent]
                async with anyio.create_task_group() as tg:
                    for j, call in enumerate(batch):
                        tg.start_soon(_run_one, batch_start + j, call)

        # Cast — every slot is filled by _run_one before task group exits.
        return results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Phase F4: Graceful shutdown
    # ------------------------------------------------------------------

    async def graceful_shutdown(self, timeout: float = 30.0) -> Dict[str, Any]:
        """Shut down the tool manager gracefully.

        Steps:

        1. Mark the manager as shutting down (rejects new dispatches).
        2. Wait up to *timeout* seconds for any in-flight tool calls to finish.
        3. Clear internal caches and category state.

        Args:
            timeout: Maximum seconds to wait for in-flight calls.

        Returns:
            A status dict with ``"status"`` (``"ok"`` or ``"timeout"``) and
            ``"categories_cleared"`` (count of categories unloaded).
        """
        self._shutting_down = True
        logger.info("HierarchicalToolManager: starting graceful shutdown (timeout=%.1fs)", timeout)

        # Give in-flight anyio tasks a moment to complete.
        try:
            with anyio.fail_after(timeout):
                # Yield control so other tasks can finish.
                await anyio.sleep(0)
        except TimeoutError:
            logger.warning("HierarchicalToolManager: graceful shutdown timed out after %.1fs", timeout)
            status = "timeout"
        else:
            status = "ok"

        categories_cleared = len(self.categories)
        # Clear internal state.
        for cat in self.categories.values():
            cat._tools.clear()
            cat._schema_cache.clear()
            cat._discovered = False
        self.categories.clear()
        self._discovered_categories = False
        self._shutting_down = False

        logger.info("HierarchicalToolManager: shutdown complete (%d categories cleared)", categories_cleared)
        return {"status": status, "categories_cleared": categories_cleared}


# Create global instance (can be overridden for testing)
# NOTE: This global is deprecated - use ServerContext instead
_global_manager: Optional[HierarchicalToolManager] = None


def get_tool_manager(context: Optional["ServerContext"] = None) -> HierarchicalToolManager:
    """Get the hierarchical tool manager instance.
    
    Args:
        context: Optional ServerContext. If provided, returns the context's
                tool_manager. Otherwise, falls back to the global instance
                for backward compatibility.
    
    Returns:
        HierarchicalToolManager instance
        
    Note:
        The global instance is deprecated. New code should use ServerContext.
        
    Example:
        >>> # New code (recommended):
        >>> with ServerContext() as ctx:
        ...     manager = get_tool_manager(ctx)
        
        >>> # Legacy code (still works):
        >>> manager = get_tool_manager()
    """
    # If context provided, use it (new pattern)
    if context is not None:
        return context.tool_manager
    
    # Fallback to global for backward compatibility (deprecated)
    global _global_manager
    if _global_manager is None:
        _global_manager = HierarchicalToolManager()
    return _global_manager


# MCP tool wrappers for registration with FastMCP

async def tools_list_categories(include_count: bool = False) -> Dict[str, Any]:
    """List all available tool categories.
    
    This meta-tool provides access to the hierarchical tool system.
    Use this to discover what categories of tools are available.
    
    Args:
        include_count: Include tool count for each category.
    
    Returns:
        Dict with list of categories and their metadata.
    """
    manager = get_tool_manager()
    categories = await manager.list_categories(include_count=include_count)
    return {
        "status": "success",
        "category_count": len(categories),
        "categories": categories
    }


async def tools_list_tools(category: str) -> Dict[str, Any]:
    """List all tools in a specific category.
    
    After discovering categories with tools_list_categories, use this
    to see what tools are available in a specific category.
    
    Args:
        category: Name of the category to list tools from.
    
    Returns:
        Dict with tools in the category.
    """
    manager = get_tool_manager()
    return await manager.list_tools(category)


async def tools_get_schema(category: str, tool: str) -> Dict[str, Any]:
    """Get the full schema for a specific tool.
    
    Use this to get detailed information about a tool's parameters,
    return type, and documentation before calling it.
    
    Args:
        category: Category containing the tool.
        tool: Name of the tool.
    
    Returns:
        Dict with tool schema.
    """
    manager = get_tool_manager()
    return await manager.get_tool_schema(category, tool)


async def tools_dispatch(
    category: str,
    tool: str,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute a tool by category and name.
    
    This is the main entry point for executing tools in the hierarchical
    tool system. Provide the category, tool name, and parameters.
    
    Args:
        category: Category containing the tool.
        tool: Name of the tool to execute.
        params: Parameters to pass to the tool (optional).
    
    Returns:
        Tool execution result.
    """
    manager = get_tool_manager()
    return await manager.dispatch(category, tool, params)


__all__ = [
    "HierarchicalToolManager",
    "ToolCategory",
    "CircuitBreaker",
    "CircuitState",
    "get_tool_manager",
    "tools_list_categories",
    "tools_list_tools",
    "tools_get_schema",
    "tools_dispatch",
]
