"""
v12 Session W80: HierarchicalToolManager — schema cache, lazy load, dispatch_with_trace.

Tests:
 - ToolCategory.get_tool_schema  — cache miss → cache hit path
 - ToolCategory.clear_schema_cache / cache_info
 - HierarchicalToolManager.get_tool_schema  — success + error paths
 - HierarchicalToolManager.lazy_register_category + lazy get_category path
 - HierarchicalToolManager._get_result_cache — graceful ImportError
 - HierarchicalToolManager.dispatch  — shutting_down guard, tool not found,
   TypeError/ValueError params, successful sync tool, successful async tool
 - HierarchicalToolManager.get_tool_schema_cid  — success + error
 - HierarchicalToolManager.dispatch_with_trace  — _trace key present
 - Module-level wrappers: tools_get_schema, tools_dispatch
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio

# ─── helpers ─────────────────────────────────────────────────────────────────

def _make_category(tools: dict) -> Any:
    """Return a ToolCategory-like object with a known set of tools."""
    from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import ToolCategory

    cat = object.__new__(ToolCategory)
    cat.name = "test_cat"
    cat.path = Path("/tmp/test_cat")
    cat.description = "Test category"
    cat._tools = tools
    cat._tool_metadata = {
        name: {"name": name, "description": f"{name} tool"}
        for name in tools
    }
    cat._discovered = True
    cat._schema_cache: dict = {}
    cat._cache_hits = 0
    cat._cache_misses = 0
    return cat


def _make_manager_with_category(cat_name: str, cat):
    """Return an HTM with one pre-loaded category."""
    from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

    mgr = object.__new__(HierarchicalToolManager)
    mgr.tools_root = Path("/tmp/test_tools")
    mgr.categories = {cat_name: cat}
    mgr._category_metadata = {cat_name: {"name": cat_name, "description": "", "path": ""}}
    mgr._discovered_categories = True
    mgr._lazy_loaders: dict = {}
    mgr._shutting_down = False
    mgr._result_cache = None
    return mgr


# ─── ToolCategory.get_tool_schema cache hit/miss ──────────────────────────────

class TestToolCategorySchemaCache:

    def test_cache_miss_then_hit(self):
        def my_tool(x: int, y: str = "default") -> Dict[str, Any]:
            return {"result": x}

        cat = _make_category({"my_tool": my_tool})
        # First call — cache miss
        schema1 = cat.get_tool_schema("my_tool")
        assert schema1 is not None
        assert "parameters" in schema1
        assert cat._cache_misses == 1
        assert cat._cache_hits == 0

        # Second call — cache hit
        schema2 = cat.get_tool_schema("my_tool")
        assert schema2 is schema1  # same object
        assert cat._cache_hits == 1
        assert cat._cache_misses == 1

    def test_cache_cleared(self):
        def simple() -> None:
            pass

        cat = _make_category({"simple": simple})
        cat.get_tool_schema("simple")
        assert cat._cache_misses == 1

        cat.clear_schema_cache()
        assert cat._cache_misses == 0
        assert cat._cache_hits == 0
        assert len(cat._schema_cache) == 0

    def test_cache_info_keys(self):
        cat = _make_category({})
        info = cat.cache_info()
        assert "hits" in info
        assert "misses" in info
        assert "size" in info

    def test_unknown_tool_returns_none(self):
        cat = _make_category({})
        assert cat.get_tool_schema("no_such_tool") is None

    def test_schema_has_parameter_required_flag(self):
        def greet(name: str, greeting: str = "Hello") -> str:
            return f"{greeting}, {name}"

        cat = _make_category({"greet": greet})
        schema = cat.get_tool_schema("greet")
        assert schema["parameters"]["name"]["required"] is True
        assert schema["parameters"]["greeting"]["required"] is False


# ─── HierarchicalToolManager.get_tool_schema ─────────────────────────────────

class TestHTMGetToolSchema:

    @pytest.mark.asyncio
    async def test_schema_success(self):
        def tool(x: int) -> int:
            return x * 2

        cat = _make_category({"tool": tool})
        mgr = _make_manager_with_category("my_cat", cat)
        result = await mgr.get_tool_schema("my_cat", "tool")
        assert result["status"] == "success"
        assert "schema" in result

    @pytest.mark.asyncio
    async def test_schema_unknown_category(self):
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        mgr = object.__new__(HierarchicalToolManager)
        mgr.tools_root = Path("/tmp/missing")
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False
        mgr._result_cache = None
        result = await mgr.get_tool_schema("no_cat", "no_tool")
        assert result["status"] == "error"
        assert "no_cat" in result["error"]

    @pytest.mark.asyncio
    async def test_schema_unknown_tool(self):
        cat = _make_category({})
        mgr = _make_manager_with_category("my_cat", cat)
        result = await mgr.get_tool_schema("my_cat", "missing_tool")
        assert result["status"] == "error"
        assert "missing_tool" in result["error"]


# ─── get_tool_schema_cid  (AE89) ────────────────────────────────────────────

class TestGetToolSchemaCid:

    @pytest.mark.asyncio
    async def test_returns_sha256_cid(self):
        def add(a: int, b: int) -> int:
            return a + b

        cat = _make_category({"add": add})
        mgr = _make_manager_with_category("math_tools", cat)
        cid = await mgr.get_tool_schema_cid("math_tools", "add")
        assert isinstance(cid, str)
        assert cid.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_cid_is_deterministic(self):
        def add(a: int, b: int) -> int:
            return a + b

        cat1 = _make_category({"add": add})
        mgr1 = _make_manager_with_category("math_tools", cat1)
        cat2 = _make_category({"add": add})
        mgr2 = _make_manager_with_category("math_tools", cat2)

        cid1 = await mgr1.get_tool_schema_cid("math_tools", "add")
        cid2 = await mgr2.get_tool_schema_cid("math_tools", "add")
        assert cid1 == cid2

    @pytest.mark.asyncio
    async def test_raises_value_error_for_unknown_tool(self):
        cat = _make_category({})
        mgr = _make_manager_with_category("cat", cat)
        with pytest.raises(ValueError):
            await mgr.get_tool_schema_cid("cat", "no_tool")


# ─── lazy_register_category + lazy get_category ──────────────────────────────

class TestLazyLoadCategory:

    @pytest.mark.asyncio
    async def test_lazy_loader_called_on_first_access(self):
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
            HierarchicalToolManager, ToolCategory,
        )
        mgr = object.__new__(HierarchicalToolManager)
        mgr.tools_root = Path("/tmp/test_tools")
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False
        mgr._result_cache = None

        loaded = []

        def lazy_loader():
            def my_lazy_tool() -> dict:
                return {"ok": True}

            cat = _make_category({"my_lazy_tool": my_lazy_tool})
            loaded.append(cat)
            return cat

        mgr.lazy_register_category("lazy_cat", lazy_loader)
        assert "lazy_cat" not in mgr.categories
        assert "lazy_cat" in mgr._lazy_loaders

        cat = mgr.get_category("lazy_cat")
        assert cat is not None
        assert len(loaded) == 1
        assert "lazy_cat" in mgr.categories
        assert "lazy_cat" not in mgr._lazy_loaders

    @pytest.mark.asyncio
    async def test_lazy_cat_appears_in_list_categories(self):
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        mgr = object.__new__(HierarchicalToolManager)
        mgr.tools_root = Path("/tmp/test_tools")
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False
        mgr._result_cache = None

        mgr.lazy_register_category("alpha", lambda: _make_category({}))
        cats = await mgr.list_categories()
        names = [c["name"] for c in cats]
        assert "alpha" in names

    @pytest.mark.asyncio
    async def test_lazy_cat_is_marked_lazy_true(self):
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        mgr = object.__new__(HierarchicalToolManager)
        mgr.tools_root = Path("/tmp/test_tools")
        mgr.categories = {}
        mgr._category_metadata = {}
        mgr._discovered_categories = True
        mgr._lazy_loaders = {}
        mgr._shutting_down = False
        mgr._result_cache = None

        mgr.lazy_register_category("beta", lambda: _make_category({}))
        cats = await mgr.list_categories()
        beta = next(c for c in cats if c["name"] == "beta")
        assert beta["lazy"] is True


# ─── _get_result_cache graceful ImportError ──────────────────────────────────

class TestGetResultCache:

    def test_graceful_import_error(self):
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        mgr = object.__new__(HierarchicalToolManager)
        mgr._result_cache = None

        # Simulate ImportError from result_cache module
        with patch.dict(sys.modules, {
            "ipfs_datasets_py.mcp_server.mcplusplus.result_cache": None
        }):
            result = mgr._get_result_cache()
        assert result is None

    def test_cached_on_second_call(self):
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        mgr = object.__new__(HierarchicalToolManager)
        # Pre-seed with a sentinel
        sentinel = object()
        mgr._result_cache = sentinel
        assert mgr._get_result_cache() is sentinel


# ─── dispatch — shutting_down guard ──────────────────────────────────────────

class TestDispatchShuttingDown:

    @pytest.mark.asyncio
    async def test_shutting_down_returns_error(self):
        cat = _make_category({})
        mgr = _make_manager_with_category("cat", cat)
        mgr._shutting_down = True
        result = await mgr.dispatch("cat", "tool", {})
        assert result["status"] == "error"
        assert "shutting down" in result["error"]

    @pytest.mark.asyncio
    async def test_tool_not_found_returns_error(self):
        cat = _make_category({})
        mgr = _make_manager_with_category("cat", cat)
        result = await mgr.dispatch("cat", "missing", {})
        assert result["status"] == "error"
        assert "missing" in result["error"]

    @pytest.mark.asyncio
    async def test_type_error_returns_error(self):
        def tool(x: int) -> int:
            raise TypeError("bad type")

        cat = _make_category({"tool": tool})
        mgr = _make_manager_with_category("cat", cat)
        result = await mgr.dispatch("cat", "tool", {})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_successful_sync_tool(self):
        def echo(msg: str = "hi") -> dict:
            return {"echoed": msg}

        cat = _make_category({"echo": echo})
        mgr = _make_manager_with_category("cat", cat)
        result = await mgr.dispatch("cat", "echo", {"msg": "world"})
        assert result["echoed"] == "world"
        assert "request_id" in result

    @pytest.mark.asyncio
    async def test_successful_async_tool(self):
        async def async_echo(msg: str = "hey") -> dict:
            return {"async_echoed": msg}

        cat = _make_category({"async_echo": async_echo})
        mgr = _make_manager_with_category("cat", cat)
        result = await mgr.dispatch("cat", "async_echo", {"msg": "async"})
        assert result["async_echoed"] == "async"


# ─── dispatch_with_trace  (AF90) ────────────────────────────────────────────

class TestDispatchWithTrace:

    @pytest.mark.asyncio
    async def test_trace_key_present(self):
        def greet(name: str = "world") -> dict:
            return {"greeting": f"hello {name}"}

        cat = _make_category({"greet": greet})
        mgr = _make_manager_with_category("cat", cat)
        result = await mgr.dispatch_with_trace("cat", "greet", {"name": "Alice"})
        assert "_trace" in result
        trace = result["_trace"]
        assert "intent_cid" in trace
        assert "output_cid" in trace
        assert "receipt_cid" in trace

    @pytest.mark.asyncio
    async def test_trace_intent_cid_is_stable(self):
        def stable() -> dict:
            return {"x": 1}

        cat1 = _make_category({"stable": stable})
        mgr1 = _make_manager_with_category("cat", cat1)
        cat2 = _make_category({"stable": stable})
        mgr2 = _make_manager_with_category("cat", cat2)

        r1 = await mgr1.dispatch_with_trace("cat", "stable", {})
        r2 = await mgr2.dispatch_with_trace("cat", "stable", {})
        assert r1["_trace"]["intent_cid"] == r2["_trace"]["intent_cid"]

    @pytest.mark.asyncio
    async def test_trace_envelope_is_complete(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import ExecutionEnvelope
        def ok() -> dict:
            return {"ok": True}

        cat = _make_category({"ok": ok})
        mgr = _make_manager_with_category("cat", cat)
        result = await mgr.dispatch_with_trace("cat", "ok", {})
        env = ExecutionEnvelope.from_dict(result["_trace"])
        assert env.is_complete()

    @pytest.mark.asyncio
    async def test_interface_cid_forwarded(self):
        def noop() -> dict:
            return {}

        cat = _make_category({"noop": noop})
        mgr = _make_manager_with_category("cat", cat)
        result = await mgr.dispatch_with_trace(
            "cat", "noop", {}, interface_cid="sha256:abcd"
        )
        assert result["_trace"]["interface_cid"] == "sha256:abcd"


# ─── module-level wrappers ────────────────────────────────────────────────────

class TestModuleLevelWrappers:

    @pytest.mark.asyncio
    async def test_tools_get_schema_wraps_manager(self):
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager as htm_mod

        mock_mgr = MagicMock()
        mock_mgr.get_tool_schema = AsyncMock(return_value={"status": "success", "schema": {}})
        with patch.object(htm_mod, "get_tool_manager", return_value=mock_mgr):
            result = await htm_mod.tools_get_schema("cat", "tool")
        mock_mgr.get_tool_schema.assert_awaited_once_with("cat", "tool")
        assert result == {"status": "success", "schema": {}}

    @pytest.mark.asyncio
    async def test_tools_dispatch_wraps_manager(self):
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager as htm_mod

        mock_mgr = MagicMock()
        mock_mgr.dispatch = AsyncMock(return_value={"status": "success"})
        with patch.object(htm_mod, "get_tool_manager", return_value=mock_mgr):
            result = await htm_mod.tools_dispatch("cat", "tool", {"k": "v"})
        mock_mgr.dispatch.assert_awaited_once_with("cat", "tool", {"k": "v"})
        assert result == {"status": "success"}
