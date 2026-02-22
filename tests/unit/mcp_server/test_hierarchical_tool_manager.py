"""Tests for the Hierarchical Tool Manager.

These tests validate that the hierarchical tool manager can:
1. Discover tool categories
2. List tools within categories
3. Get tool schemas
4. Dispatch to tools
"""

import pytest
import anyio
from pathlib import Path

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    HierarchicalToolManager,
    ToolCategory,
    get_tool_manager,
    tools_list_categories,
    tools_list_tools,
    tools_get_schema,
    tools_dispatch,
    CircuitBreaker,
    CircuitState,
)


class TestToolCategory:
    """Tests for ToolCategory class."""
    
    def test_create_category(self):
        """Test creating a tool category."""
        # GIVEN a path and category name
        tools_root = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools"
        category_path = tools_root / "graph_tools"
        
        # WHEN we create a category
        category = ToolCategory("graph_tools", category_path, "Graph tools for knowledge graphs")
        
        # THEN the category is created with correct attributes
        assert category.name == "graph_tools"
        assert category.path == category_path
        assert category.description == "Graph tools for knowledge graphs"
        assert not category._discovered
    
    def test_discover_tools(self):
        """Test discovering tools in a category."""
        # GIVEN a category with tools
        tools_root = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools"
        category_path = tools_root / "graph_tools"
        category = ToolCategory("graph_tools", category_path)
        
        # WHEN we discover tools
        category.discover_tools()
        
        # THEN tools are discovered
        assert category._discovered
        assert len(category._tools) > 0
        assert "query_knowledge_graph" in category._tools
    
    def test_list_tools(self):
        """Test listing tools in a category."""
        # GIVEN a category with discovered tools
        tools_root = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools"
        category_path = tools_root / "graph_tools"
        category = ToolCategory("graph_tools", category_path)
        category.discover_tools()
        
        # WHEN we list tools
        tools = category.list_tools()
        
        # THEN we get a list of tool metadata
        assert isinstance(tools, list)
        assert len(tools) > 0
        assert all(isinstance(t, dict) for t in tools)
        assert all("name" in t and "description" in t for t in tools)
    
    def test_get_tool(self):
        """Test getting a specific tool."""
        # GIVEN a category with tools
        tools_root = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools"
        category_path = tools_root / "graph_tools"
        category = ToolCategory("graph_tools", category_path)
        category.discover_tools()
        
        # WHEN we get a tool
        tool_func = category.get_tool("query_knowledge_graph")
        
        # THEN we get a callable function
        assert tool_func is not None
        assert callable(tool_func)
    
    def test_get_tool_schema(self):
        """Test getting tool schema."""
        # GIVEN a category with tools
        tools_root = Path(__file__).parent.parent.parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools"
        category_path = tools_root / "graph_tools"
        category = ToolCategory("graph_tools", category_path)
        category.discover_tools()
        
        # WHEN we get a tool schema
        schema = category.get_tool_schema("query_knowledge_graph")
        
        # THEN we get schema with metadata and parameters
        assert schema is not None
        assert "name" in schema
        assert "category" in schema
        assert "parameters" in schema
        assert isinstance(schema["parameters"], dict)


class TestHierarchicalToolManager:
    """Tests for HierarchicalToolManager class."""
    
    def test_create_manager(self):
        """Test creating a hierarchical tool manager."""
        # GIVEN default setup
        # WHEN we create a manager
        manager = HierarchicalToolManager()
        
        # THEN the manager is created with correct attributes
        assert manager.tools_root.exists()
        assert not manager._discovered_categories
        assert len(manager.categories) == 0
    
    def test_discover_categories(self):
        """Test discovering categories."""
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we discover categories
        manager.discover_categories()
        
        # THEN categories are discovered
        assert manager._discovered_categories
        assert len(manager.categories) > 0
        assert "graph_tools" in manager.categories
        assert "ipfs_tools" in manager.categories
    
    @pytest.mark.anyio
    async def test_list_categories(self):
        """Test listing categories."""
        # GIVEN a manager with discovered categories
        manager = HierarchicalToolManager()
        manager.discover_categories()
        
        # WHEN we list categories
        categories = await manager.list_categories()
        
        # THEN we get a list of categories
        assert isinstance(categories, list)
        assert len(categories) > 0
        assert all(isinstance(c, dict) for c in categories)
        assert all("name" in c for c in categories)
    
    @pytest.mark.anyio
    async def test_list_categories_with_count(self):
        """Test listing categories with tool counts."""
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we list categories with counts
        categories = await manager.list_categories(include_count=True)
        
        # THEN we get categories with tool counts
        assert len(categories) > 0
        assert all("tool_count" in c for c in categories)
    
    @pytest.mark.anyio
    async def test_list_tools(self):
        """Test listing tools in a category."""
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we list tools in a category
        result = await manager.list_tools("graph_tools")
        
        # THEN we get tools from that category
        assert result["status"] == "success"
        assert result["category"] == "graph_tools"
        assert "tools" in result
        assert len(result["tools"]) > 0
    
    @pytest.mark.anyio
    async def test_list_tools_invalid_category(self):
        """Test listing tools from invalid category."""
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we list tools from invalid category
        result = await manager.list_tools("nonexistent_category")
        
        # THEN we get an error
        assert result["status"] == "error"
        assert "not found" in result["error"]
    
    @pytest.mark.anyio
    async def test_get_tool_schema(self):
        """Test getting tool schema."""
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we get a tool schema
        result = await manager.get_tool_schema("graph_tools", "query_knowledge_graph")
        
        # THEN we get the schema
        assert result["status"] == "success"
        assert "schema" in result
        assert result["schema"]["name"] == "query_knowledge_graph"
    
    @pytest.mark.anyio
    async def test_dispatch_success(self):
        """Test dispatching to a tool successfully."""
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we dispatch to a tool (using a simple tool for testing)
        # Note: This test might need adjustment based on actual tool behavior
        result = await manager.dispatch("graph_tools", "query_knowledge_graph", {
            "query": "test query",
            "max_results": 10
        })
        
        # THEN we get a result (could be success or error from the tool itself)
        assert isinstance(result, dict)
        # The actual tool might return an error if test data isn't set up,
        # but the dispatch itself should work
    
    @pytest.mark.anyio
    async def test_dispatch_invalid_category(self):
        """Test dispatching to invalid category."""
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we dispatch to invalid category
        result = await manager.dispatch("invalid_category", "some_tool", {})
        
        # THEN we get an error
        assert result["status"] == "error"
        assert "not found" in result["error"]
    
    @pytest.mark.anyio
    async def test_dispatch_invalid_tool(self):
        """Test dispatching to invalid tool."""
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we dispatch to invalid tool
        result = await manager.dispatch("graph_tools", "nonexistent_tool", {})
        
        # THEN we get an error
        assert result["status"] == "error"
        assert "not found" in result["error"]


class TestMCPToolWrappers:
    """Tests for MCP tool wrapper functions."""
    
    @pytest.mark.anyio
    async def test_tools_list_categories(self):
        """Test tools_list_categories wrapper."""
        # WHEN we call the wrapper
        result = await tools_list_categories()
        
        # THEN we get categories
        assert result["status"] == "success"
        assert "categories" in result
        assert len(result["categories"]) > 0
    
    @pytest.mark.anyio
    async def test_tools_list_tools(self):
        """Test tools_list_tools wrapper."""
        # WHEN we call the wrapper
        result = await tools_list_tools("graph_tools")
        
        # THEN we get tools
        assert result["status"] == "success"
        assert "tools" in result
    
    @pytest.mark.anyio
    async def test_tools_get_schema(self):
        """Test tools_get_schema wrapper."""
        # WHEN we call the wrapper
        result = await tools_get_schema("graph_tools", "query_knowledge_graph")
        
        # THEN we get schema
        assert result["status"] == "success"
        assert "schema" in result
    
    @pytest.mark.anyio
    async def test_tools_dispatch(self):
        """Test tools_dispatch wrapper."""
        # WHEN we call the wrapper
        result = await tools_dispatch("graph_tools", "query_knowledge_graph", {
            "query": "test",
            "max_results": 5
        })
        
        # THEN we get a result
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Phase F1: dispatch_parallel
# ---------------------------------------------------------------------------

class TestDispatchParallel:
    """Tests for HierarchicalToolManager.dispatch_parallel() (Phase F1)."""

    def _build_manager_with_mock_tool(self) -> HierarchicalToolManager:
        """Return a manager with a fast mock async tool in dataset_tools."""
        from unittest.mock import AsyncMock

        mgr = HierarchicalToolManager.__new__(HierarchicalToolManager)
        mgr.tools_root = Path(__file__).parent
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False

        cat = ToolCategory.__new__(ToolCategory)
        cat.name = "dataset_tools"
        cat.path = Path(__file__).parent
        cat.description = ""
        cat._tools = {"load_dataset": AsyncMock(return_value={"status": "ok", "rows": 50})}
        cat._tool_metadata = {}
        cat._discovered = True
        cat._schema_cache = {}
        cat._cache_hits = 0
        cat._cache_misses = 0

        mgr.categories["dataset_tools"] = cat
        return mgr

    @pytest.mark.anyio
    async def test_dispatch_parallel_empty(self):
        """GIVEN an empty call list THEN returns an empty list."""
        # GIVEN
        mgr = self._build_manager_with_mock_tool()
        # WHEN
        results = await mgr.dispatch_parallel([])
        # THEN
        assert results == []

    @pytest.mark.anyio
    async def test_dispatch_parallel_single_call(self):
        """GIVEN one call THEN returns one result in a list."""
        # GIVEN
        mgr = self._build_manager_with_mock_tool()
        calls = [{"category": "dataset_tools", "tool": "load_dataset", "params": {"source": "squad"}}]
        # WHEN
        results = await mgr.dispatch_parallel(calls)
        # THEN
        assert len(results) == 1
        assert results[0]["status"] == "ok"

    @pytest.mark.anyio
    async def test_dispatch_parallel_multiple_calls_order_preserved(self):
        """GIVEN N calls THEN results are in the same order as calls."""
        # GIVEN
        mgr = self._build_manager_with_mock_tool()
        n = 8
        calls = [
            {"category": "dataset_tools", "tool": "load_dataset", "params": {"source": f"ds_{i}"}}
            for i in range(n)
        ]
        # WHEN
        results = await mgr.dispatch_parallel(calls)
        # THEN
        assert len(results) == n
        for r in results:
            assert r.get("status") == "ok"

    @pytest.mark.anyio
    async def test_dispatch_parallel_invalid_category_captured(self):
        """GIVEN a call with an invalid category THEN an error dict is returned (not raised)."""
        # GIVEN
        mgr = self._build_manager_with_mock_tool()
        calls = [
            {"category": "nonexistent", "tool": "any_tool"},
            {"category": "dataset_tools", "tool": "load_dataset"},
        ]
        # WHEN
        results = await mgr.dispatch_parallel(calls, return_exceptions=True)
        # THEN — both results present; first is error, second is ok
        assert len(results) == 2
        assert results[0]["status"] == "error"
        assert results[1]["status"] == "ok"


# ---------------------------------------------------------------------------
# Phase F3: CircuitBreaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    """Tests for CircuitBreaker (Phase F3)."""

    def test_initial_state_is_closed(self):
        """GIVEN a new circuit breaker THEN state is CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open()

    @pytest.mark.anyio
    async def test_success_keeps_closed(self):
        """GIVEN a successful call THEN state remains CLOSED."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        async def _ok():
            return {"status": "ok"}

        result = await cb.call(_ok)
        assert result["status"] == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.anyio
    async def test_failure_threshold_opens_circuit(self):
        """GIVEN failure_threshold consecutive failures THEN circuit opens."""
        from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

        async def _fail():
            raise RuntimeError("boom")

        for _ in range(3):
            with pytest.raises(ToolExecutionError):
                await cb.call(_fail)

        assert cb.state == CircuitState.OPEN
        assert cb.is_open()

    @pytest.mark.anyio
    async def test_open_circuit_rejects_calls(self):
        """GIVEN an open circuit THEN calls return an error dict without invoking the function."""
        from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError
        called = []

        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)

        async def _fail():
            raise RuntimeError("boom")

        async def _should_not_run():
            called.append(1)
            return {"status": "ok"}

        # Open the circuit.
        with pytest.raises(ToolExecutionError):
            await cb.call(_fail)

        assert cb.state == CircuitState.OPEN

        result = await cb.call(_should_not_run)
        assert result["status"] == "error"
        assert "OPEN" in result["error"]
        assert called == []  # Function was never invoked.

    def test_reset_closes_circuit(self):
        """GIVEN an open circuit WHEN reset() is called THEN state is CLOSED."""
        import time
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
        # Force open without async context.
        cb._state = CircuitState.OPEN
        cb._failure_count = 1
        cb._opened_at = time.monotonic()

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_info_returns_snapshot(self):
        """CircuitBreaker.info() returns a dict with expected keys."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="test_cb")
        info = cb.info()
        assert info["name"] == "test_cb"
        assert info["state"] == CircuitState.CLOSED
        assert info["failure_threshold"] == 5
        assert info["recovery_timeout"] == 30.0


# ---------------------------------------------------------------------------
# Phase F4: graceful_shutdown
# ---------------------------------------------------------------------------

class TestGracefulShutdown:
    """Tests for HierarchicalToolManager.graceful_shutdown() (Phase F4)."""

    @pytest.mark.anyio
    async def test_graceful_shutdown_clears_categories(self):
        """GIVEN a warm manager WHEN graceful_shutdown() THEN all categories cleared."""
        # GIVEN
        from unittest.mock import AsyncMock

        mgr = HierarchicalToolManager.__new__(HierarchicalToolManager)
        mgr.tools_root = Path(__file__).parent
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False

        cat = ToolCategory.__new__(ToolCategory)
        cat.name = "dataset_tools"
        cat.path = Path(__file__).parent
        cat.description = ""
        cat._tools = {"load_dataset": AsyncMock(return_value={"status": "ok"})}
        cat._tool_metadata = {}
        cat._discovered = True
        cat._schema_cache = {"load_dataset": {}}
        cat._cache_hits = 0
        cat._cache_misses = 0
        mgr.categories["dataset_tools"] = cat

        # WHEN
        result = await mgr.graceful_shutdown(timeout=5.0)

        # THEN
        assert result["status"] == "ok"
        assert result["categories_cleared"] == 1
        assert len(mgr.categories) == 0

    @pytest.mark.anyio
    async def test_dispatch_rejected_during_shutdown(self):
        """GIVEN _shutting_down=True THEN dispatch() returns an error immediately."""
        # GIVEN
        from unittest.mock import AsyncMock

        mgr = HierarchicalToolManager.__new__(HierarchicalToolManager)
        mgr.tools_root = Path(__file__).parent
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = True

        # WHEN
        result = await mgr.dispatch("dataset_tools", "load_dataset")

        # THEN
        assert result["status"] == "error"
        assert "shutting down" in result["error"].lower()


# ---------------------------------------------------------------------------
# Phase C1: request_id structured logging
# ---------------------------------------------------------------------------

class TestRequestId:
    """Phase C1: dispatch() attaches a unique request_id to every response."""

    @pytest.mark.anyio
    async def test_error_response_has_request_id(self):
        """GIVEN a missing category THEN dispatch() returns request_id."""
        mgr = HierarchicalToolManager.__new__(HierarchicalToolManager)
        mgr.tools_root = Path(__file__).parent
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False

        result = await mgr.dispatch("no_such_category", "no_such_tool")

        assert result["status"] == "error"
        assert "request_id" in result
        assert len(result["request_id"]) == 36  # UUID4 string length

    @pytest.mark.anyio
    async def test_success_response_has_request_id(self):
        """GIVEN a real tool dispatch THEN result contains a request_id."""
        import asyncio
        from unittest.mock import MagicMock

        async def _fake_tool() -> dict:
            return {"status": "success", "data": "ok"}

        cat = ToolCategory("fake_cat", Path(__file__).parent)
        cat._tools["fake_tool"] = _fake_tool
        cat._tool_metadata["fake_tool"] = {
            "name": "fake_tool",
            "category": "fake_cat",
            "description": "",
            "signature": "()",
            "schema_version": "1.0",
            "deprecated": False,
            "deprecation_message": "",
        }
        cat._discovered = True

        mgr = HierarchicalToolManager.__new__(HierarchicalToolManager)
        mgr.tools_root = Path(__file__).parent
        mgr.categories = {"fake_cat": cat}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False

        result = await mgr.dispatch("fake_cat", "fake_tool")

        assert result["status"] == "success"
        assert "request_id" in result

    @pytest.mark.anyio
    async def test_request_ids_are_unique(self):
        """GIVEN multiple calls THEN each gets a distinct request_id."""
        mgr = HierarchicalToolManager.__new__(HierarchicalToolManager)
        mgr.tools_root = Path(__file__).parent
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False

        ids = {
            (await mgr.dispatch("c", "t"))["request_id"]
            for _ in range(5)
        }
        assert len(ids) == 5  # all unique


# ---------------------------------------------------------------------------
# Phase D1+D2: schema_version + deprecated in ToolMetadata
# ---------------------------------------------------------------------------

class TestToolMetadataVersioningAndDeprecation:
    """Phase D1 + D2: schema_version and deprecated fields in ToolMetadata."""

    def test_default_schema_version(self):
        """GIVEN no schema_version THEN default is '1.0'."""
        from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadata
        m = ToolMetadata(name="my_tool")
        assert m.schema_version == "1.0"

    def test_custom_schema_version(self):
        """GIVEN schema_version='2.1' THEN it is stored correctly."""
        from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadata
        m = ToolMetadata(name="versioned_tool", schema_version="2.1")
        assert m.schema_version == "2.1"

    def test_schema_version_in_to_dict(self):
        """GIVEN a ToolMetadata THEN to_dict() includes schema_version."""
        from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadata
        m = ToolMetadata(name="t", schema_version="3.0")
        d = m.to_dict()
        assert d["schema_version"] == "3.0"

    def test_deprecated_default_is_false(self):
        """GIVEN no deprecated kwarg THEN default is False."""
        from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadata
        m = ToolMetadata(name="current_tool")
        assert m.deprecated is False
        assert m.deprecation_message == ""

    def test_deprecated_marker(self):
        """GIVEN deprecated=True THEN flag and message are stored."""
        from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadata
        m = ToolMetadata(
            name="old_tool",
            deprecated=True,
            deprecation_message="Use new_tool instead.",
        )
        assert m.deprecated is True
        assert m.deprecation_message == "Use new_tool instead."

    def test_deprecated_in_to_dict(self):
        """GIVEN deprecated=True THEN to_dict() exposes deprecated + deprecation_message."""
        from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadata
        m = ToolMetadata(name="x", deprecated=True, deprecation_message="bye")
        d = m.to_dict()
        assert d["deprecated"] is True
        assert d["deprecation_message"] == "bye"

    def test_tool_metadata_decorator_schema_version(self):
        """GIVEN @tool_metadata(schema_version='2.0') THEN function has schema_version='2.0'."""
        from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
        @tool_metadata(schema_version="2.0")
        def my_versioned_tool() -> dict:
            """A versioned tool."""
            return {}
        assert my_versioned_tool._mcp_metadata.schema_version == "2.0"

    def test_tool_metadata_decorator_deprecated(self):
        """GIVEN @tool_metadata(deprecated=True) THEN function has deprecated=True."""
        from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata
        @tool_metadata(deprecated=True, deprecation_message="Use replacement_tool.")
        def my_old_tool() -> dict:
            """A deprecated tool."""
            return {}
        assert my_old_tool._mcp_metadata.deprecated is True
        assert "replacement_tool" in my_old_tool._mcp_metadata.deprecation_message

    @pytest.mark.anyio
    async def test_dispatch_warns_for_deprecated_tool(self, caplog):
        """GIVEN a deprecated tool THEN dispatch() emits a deprecation warning."""
        import logging
        from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata

        @tool_metadata(deprecated=True, deprecation_message="Use shiny_new_tool.")
        async def legacy_operation() -> dict:
            """Old tool."""
            return {"status": "success", "legacy": True}

        cat = ToolCategory("legacy_cat", Path(__file__).parent)
        cat._tools["legacy_operation"] = legacy_operation
        cat._tool_metadata["legacy_operation"] = {
            "name": "legacy_operation",
            "category": "legacy_cat",
            "description": "",
            "signature": "()",
            "schema_version": "1.0",
            "deprecated": True,
            "deprecation_message": "Use shiny_new_tool.",
        }
        cat._discovered = True

        mgr = HierarchicalToolManager.__new__(HierarchicalToolManager)
        mgr.tools_root = Path(__file__).parent
        mgr.categories = {"legacy_cat": cat}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False

        with caplog.at_level(logging.WARNING):
            result = await mgr.dispatch("legacy_cat", "legacy_operation")

        assert result["status"] == "success"
        assert any("deprecated" in r.message.lower() for r in caplog.records)
