"""Phase H45 — Integration: GraphRAG + IPFS combined pipeline scenario.

This test file simulates a multi-stage AI document-processing pipeline that
mirrors the real GraphRAG + IPFS workflow:

  1. Ingest a document (pdf_tools/extract_text)
  2. Build a knowledge graph (graph_tools/build_graph)
  3. Pin the graph artefact to IPFS (ipfs_tools/pin_content)
  4. Query the graph (graph_tools/query)
  5. Search document sections (search_tools/semantic_search)

All external dependencies are mocked so the test exercises the *orchestration*
layer — i.e. HierarchicalToolManager.dispatch_parallel, graceful_shutdown, and
the ToolCategory discovery helpers — rather than the real AI/IPFS back-ends.

Additionally covers the remaining uncovered lines:
- ToolCategory.discover_tools import errors (lines 260-265)
- ToolCategory.get_tool_schema caching (lines 317-319, 327, 360-361)
- ToolCategory.clear_schema_cache + cache_info (lines 364-383)
- HierarchicalToolManager.lazy_register_category (lines 520-545)
- HierarchicalToolManager.get_category lazy-load path (lines 559-568)
- HierarchicalToolManager.list_categories include_count branch (lines 594-599)
- HierarchicalToolManager.list_tools category-not-found (lines 618-623)
- HierarchicalToolManager.get_tool_schema both branches (lines 648-665)
- HierarchicalToolManager.dispatch shutting-down (line 689)
- HierarchicalToolManager.graceful_shutdown (lines 927-952)

Test Format: GIVEN-WHEN-THEN
"""

import asyncio
import importlib
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, Mock, MagicMock, patch
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    HierarchicalToolManager,
    ToolCategory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mgr(tmp_path: Path) -> HierarchicalToolManager:
    mgr = HierarchicalToolManager(tmp_path)
    mgr._discovered_categories = True
    return mgr


def _add_tool(mgr: HierarchicalToolManager, cat: str, tool_name: str, fn) -> None:
    mock_cat = Mock(spec=ToolCategory)
    mock_cat.get_tool.return_value = fn
    mock_cat.list_tools.return_value = [{"name": tool_name}]
    mgr.categories[cat] = mock_cat


# ---------------------------------------------------------------------------
# Part 1 — GraphRAG + IPFS multi-step pipeline
# ---------------------------------------------------------------------------

class TestGraphRAGIPFSPipeline:
    """Simulate the five-stage document→graph→IPFS→query→search pipeline."""

    @pytest.mark.asyncio
    async def test_five_stage_pipeline_all_succeed(self, tmp_path):
        """GIVEN five mocked pipeline-stage tools (extract, build_graph, pin, query, search)
        WHEN dispatch_parallel fires all five concurrently
        THEN every stage returns status=success and results arrive in order.
        """
        mgr = _mgr(tmp_path)

        def extract_text(doc_path: str = "") -> Dict[str, Any]:
            return {"status": "success", "stage": "extract", "text": "lorem ipsum"}

        def build_graph(text: str = "") -> Dict[str, Any]:
            return {"status": "success", "stage": "build_graph", "node_count": 42}

        async def pin_content(content: str = "") -> Dict[str, Any]:
            await asyncio.sleep(0)
            return {"status": "success", "stage": "pin", "cid": "QmFakeCID"}

        def query_graph(query: str = "") -> Dict[str, Any]:
            return {"status": "success", "stage": "query", "hits": 7}

        async def semantic_search(query: str = "") -> Dict[str, Any]:
            await asyncio.sleep(0)
            return {"status": "success", "stage": "search", "results": ["doc1", "doc2"]}

        _add_tool(mgr, "pdf_tools", "extract_text", extract_text)
        _add_tool(mgr, "graph_tools_build", "build_graph", build_graph)
        _add_tool(mgr, "ipfs_tools", "pin_content", pin_content)
        _add_tool(mgr, "graph_tools_query", "query_graph", query_graph)
        _add_tool(mgr, "search_tools", "semantic_search", semantic_search)

        calls = [
            {"category": "pdf_tools",         "tool": "extract_text",   "params": {"doc_path": "/tmp/test.pdf"}},
            {"category": "graph_tools_build",  "tool": "build_graph",    "params": {"text": "lorem ipsum"}},
            {"category": "ipfs_tools",         "tool": "pin_content",    "params": {"content": "graph_bytes"}},
            {"category": "graph_tools_query",  "tool": "query_graph",    "params": {"query": "contract terms"}},
            {"category": "search_tools",       "tool": "semantic_search","params": {"query": "obligations"}},
        ]

        results = await mgr.dispatch_parallel(calls)

        # THEN
        assert len(results) == 5
        stages = [r["stage"] for r in results]
        assert stages == ["extract", "build_graph", "pin", "query", "search"]
        assert all(r["status"] == "success" for r in results)

    @pytest.mark.asyncio
    async def test_ipfs_failure_captured_others_succeed(self, tmp_path):
        """GIVEN a pipeline where the IPFS pin stage fails
        WHEN dispatch_parallel runs (return_exceptions=True)
        THEN only the pin slot has an error; all other stages succeed.
        """
        mgr = _mgr(tmp_path)

        def ok_tool() -> Dict[str, Any]:
            return {"status": "success"}

        def bad_pin():
            raise ConnectionError("IPFS node unreachable")

        _add_tool(mgr, "pcat1", "ok_tool", ok_tool)
        _add_tool(mgr, "pcat_bad", "bad_pin", bad_pin)
        _add_tool(mgr, "pcat2", "ok_tool", ok_tool)

        calls = [
            {"category": "pcat1",    "tool": "ok_tool"},
            {"category": "pcat_bad", "tool": "bad_pin"},
            {"category": "pcat2",    "tool": "ok_tool"},
        ]
        results = await mgr.dispatch_parallel(calls)

        assert results[0]["status"] == "success"
        assert results[1]["status"] == "error"
        assert results[2]["status"] == "success"

    @pytest.mark.asyncio
    async def test_pipeline_result_fed_into_next_dispatch(self, tmp_path):
        """GIVEN a two-stage pipeline where stage-2 uses stage-1 output
        WHEN we await stage-1 then pass its result to stage-2
        THEN the combined output is consistent.
        """
        mgr = _mgr(tmp_path)

        def stage1(source: str = "") -> Dict[str, Any]:
            return {"status": "success", "cid": f"Qm{source[:4]}"}

        async def stage2(cid: str = "") -> Dict[str, Any]:
            return {"status": "success", "graph_url": f"ipfs://{cid}"}

        _add_tool(mgr, "s1cat", "stage1", stage1)
        _add_tool(mgr, "s2cat", "stage2", stage2)

        # Stage 1
        r1 = await mgr.dispatch_parallel(
            [{"category": "s1cat", "tool": "stage1", "params": {"source": "docXY"}}]
        )
        assert r1[0]["status"] == "success"
        cid = r1[0]["cid"]

        # Stage 2 uses cid from stage 1
        r2 = await mgr.dispatch_parallel(
            [{"category": "s2cat", "tool": "stage2", "params": {"cid": cid}}]
        )
        assert r2[0]["status"] == "success"
        assert cid in r2[0]["graph_url"]


# ---------------------------------------------------------------------------
# Part 2 — graceful_shutdown
# ---------------------------------------------------------------------------

class TestGracefulShutdown:
    """Verify HierarchicalToolManager.graceful_shutdown (lines 927-952)."""

    @pytest.mark.asyncio
    async def test_shutdown_clears_categories(self, tmp_path):
        """GIVEN a manager with 3 registered categories
        WHEN graceful_shutdown is called
        THEN categories are cleared and status is 'ok'.
        """
        mgr = _mgr(tmp_path)

        for i in range(3):
            mock_cat = Mock(spec=ToolCategory)
            mock_cat._tools = {f"tool{i}": lambda: None}
            mock_cat._schema_cache = {}
            mock_cat._discovered = True
            mgr.categories[f"cat{i}"] = mock_cat

        result = await mgr.graceful_shutdown(timeout=5.0)

        assert result["status"] == "ok"
        assert result["categories_cleared"] == 3
        assert len(mgr.categories) == 0
        assert mgr._discovered_categories is False
        assert mgr._shutting_down is False

    @pytest.mark.asyncio
    async def test_shutdown_with_zero_categories(self, tmp_path):
        """GIVEN a manager with no categories
        WHEN graceful_shutdown is called
        THEN categories_cleared == 0 and status is 'ok'.
        """
        mgr = _mgr(tmp_path)
        result = await mgr.graceful_shutdown(timeout=1.0)
        assert result["status"] == "ok"
        assert result["categories_cleared"] == 0

    @pytest.mark.asyncio
    async def test_dispatch_rejected_during_shutdown(self, tmp_path):
        """GIVEN a manager that is in the middle of shutting down
        WHEN dispatch() is called while _shutting_down=True
        THEN an error dict mentioning shutdown is returned.
        """
        mgr = _mgr(tmp_path)
        mgr._shutting_down = True

        result = await mgr.dispatch("any_cat", "any_tool", {})
        assert result["status"] == "error"
        assert "shutting down" in result["error"].lower()

        mgr._shutting_down = False  # cleanup


# ---------------------------------------------------------------------------
# Part 3 — ToolCategory discovery error paths
# ---------------------------------------------------------------------------

class TestToolCategoryDiscoveryErrors:
    """Verify that discovery continues gracefully when files cannot be imported."""

    def test_import_error_logged_and_skipped(self, tmp_path):
        """GIVEN a category directory containing a tool file that raises ImportError
        WHEN discover_tools is called
        THEN the error is logged, the file is skipped, and _discovered is set True.
        """
        # GIVEN: create a Python file whose stem matches the tool convention
        tool_file = tmp_path / "bad_tool.py"
        tool_file.write_text("raise ImportError('missing dep')\n")

        cat = ToolCategory("test_cat", tmp_path)

        # WHEN
        with patch("ipfs_datasets_py.mcp_server.hierarchical_tool_manager.importlib.import_module",
                   side_effect=ImportError("missing dep")):
            cat.discover_tools()

        # THEN: discovery completed without crashing
        assert cat._discovered is True

    def test_syntax_error_in_tool_file_skipped(self, tmp_path):
        """GIVEN a category directory containing a syntactically broken file
        WHEN discover_tools is called
        THEN the error is logged and discovery still completes.
        """
        # Create a non-hidden Python file so glob("*.py") finds at least one entry.
        # importlib.import_module is mocked to raise SyntaxError, so file content
        # is irrelevant — it never gets parsed.
        (tmp_path / "broken_tool.py").write_text("# placeholder\n")

        cat = ToolCategory("test_cat", tmp_path)
        with patch("ipfs_datasets_py.mcp_server.hierarchical_tool_manager.importlib.import_module",
                   side_effect=SyntaxError("invalid syntax")):
            cat.discover_tools()

        assert cat._discovered is True

    def test_generic_exception_in_tool_file_skipped(self, tmp_path):
        """GIVEN a category directory containing a file that causes a generic Exception on import
        WHEN discover_tools is called
        THEN the error is logged and discovery still completes.
        """
        # Create a non-hidden Python file so glob("*.py") finds at least one entry.
        # importlib.import_module is mocked to raise Exception, so file content
        # is irrelevant — it represents any unexpected import-time failure.
        (tmp_path / "generic_err_tool.py").write_text("# placeholder\n")

        cat = ToolCategory("test_cat", tmp_path)
        with patch("ipfs_datasets_py.mcp_server.hierarchical_tool_manager.importlib.import_module",
                   side_effect=Exception("oops")):
            cat.discover_tools()

        assert cat._discovered is True

    def test_nonexistent_path_skips_discovery(self):
        """GIVEN a category whose path does not exist on disk
        WHEN discover_tools is called
        THEN _discovered remains False (path does not exist, early return).
        """
        cat = ToolCategory("ghost_cat", Path("/nonexistent/path/xyz"))
        cat.discover_tools()
        # Early return branch: _discovered is NOT set to True
        assert cat._discovered is False


# ---------------------------------------------------------------------------
# Part 4 — ToolCategory schema cache
# ---------------------------------------------------------------------------

class TestToolCategorySchemaCache:
    """Verify get_tool_schema caching paths (lines 317-319, 360-361)."""

    def test_schema_cache_hit_path(self):
        """GIVEN a category with a pre-populated schema cache
        WHEN get_tool_schema is called for the cached tool
        THEN the cached schema is returned and _cache_hits increments.
        """
        cat = ToolCategory("test", Path("/tmp"))
        cat._discovered = True
        cat._schema_cache["my_tool"] = {"name": "my_tool", "cached": True}

        result = cat.get_tool_schema("my_tool")
        assert result == {"name": "my_tool", "cached": True}
        assert cat._cache_hits == 1

    def test_schema_cache_miss_builds_and_stores(self):
        """GIVEN a category with a real tool function
        WHEN get_tool_schema is called
        THEN a schema is built, stored in cache, and _cache_misses increments.
        """
        def my_tool(x: int, y: str = "default") -> str:
            """My tool docstring."""
            return f"{x} {y}"

        cat = ToolCategory("test", Path("/tmp"))
        cat._discovered = True
        cat._tools["my_tool"] = my_tool
        cat._tool_metadata["my_tool"] = {
            "name": "my_tool",
            "category": "test",
            "description": "My tool docstring.",
            "signature": str(__import__("inspect").signature(my_tool)),
            "schema_version": "1.0",
            "deprecated": False,
            "deprecation_message": "",
        }

        result = cat.get_tool_schema("my_tool")

        assert result is not None
        assert result["name"] == "my_tool"
        assert "parameters" in result
        assert "x" in result["parameters"]
        assert cat._cache_misses == 1
        assert "my_tool" in cat._schema_cache

    def test_schema_second_call_uses_cache(self):
        """GIVEN a category where a schema was already fetched once
        WHEN get_tool_schema is called again
        THEN cache_hits increments (no duplicate build).
        """
        def simple(n: int) -> int:
            return n

        cat = ToolCategory("test", Path("/tmp"))
        cat._discovered = True
        cat._tools["simple"] = simple
        cat._tool_metadata["simple"] = {
            "name": "simple",
            "category": "test",
            "description": "",
            "signature": "(n: int) -> int",
            "schema_version": "1.0",
            "deprecated": False,
            "deprecation_message": "",
        }

        cat.get_tool_schema("simple")   # first call → miss
        cat.get_tool_schema("simple")   # second call → hit

        assert cat._cache_hits == 1
        assert cat._cache_misses == 1

    def test_clear_schema_cache(self):
        """GIVEN a category with a populated schema cache and hit/miss counters
        WHEN clear_schema_cache() is called
        THEN cache is empty and counters reset to zero.
        """
        cat = ToolCategory("test", Path("/tmp"))
        cat._schema_cache["x"] = {"name": "x"}
        cat._cache_hits = 3
        cat._cache_misses = 2

        cat.clear_schema_cache()

        assert len(cat._schema_cache) == 0
        assert cat._cache_hits == 0
        assert cat._cache_misses == 0

    def test_cache_info(self):
        """GIVEN a category with known cache statistics
        WHEN cache_info() is called
        THEN returned dict has hits, misses, and size keys.
        """
        cat = ToolCategory("test", Path("/tmp"))
        cat._schema_cache["a"] = {}
        cat._schema_cache["b"] = {}
        cat._cache_hits = 5
        cat._cache_misses = 1

        info = cat.cache_info()
        assert info["hits"] == 5
        assert info["misses"] == 1
        assert info["size"] == 2

    def test_get_tool_schema_unknown_tool_returns_none(self):
        """GIVEN a category with no tools
        WHEN get_tool_schema is called for an unknown tool
        THEN None is returned.
        """
        cat = ToolCategory("test", Path("/tmp"))
        cat._discovered = True
        result = cat.get_tool_schema("ghost_tool")
        assert result is None


# ---------------------------------------------------------------------------
# Part 5 — lazy_register_category + get_category lazy-load
# ---------------------------------------------------------------------------

class TestLazyRegisterCategory:
    """Verify lazy category registration (lines 520-568)."""

    @pytest.mark.asyncio
    async def test_lazy_registered_category_appears_in_list(self, tmp_path):
        """GIVEN a lazy-registered category
        WHEN list_categories is called
        THEN the category name appears in the listing with lazy=True.
        """
        mgr = _mgr(tmp_path)
        mock_cat = Mock(spec=ToolCategory)
        mock_cat.description = "lazy cat"
        mock_cat.path = tmp_path

        mgr.lazy_register_category("lazy_cat", lambda: mock_cat)
        result = await mgr.list_categories()

        names = [c["name"] for c in result]
        assert "lazy_cat" in names

    def test_get_category_triggers_lazy_loader(self, tmp_path):
        """GIVEN a lazy-registered category
        WHEN get_category is called
        THEN the loader is invoked and the category is added to self.categories.
        """
        mgr = _mgr(tmp_path)

        mock_cat = Mock(spec=ToolCategory)
        mock_cat.description = "loaded-on-demand"
        mock_cat.path = tmp_path
        loader_called = []

        def loader():
            loader_called.append(1)
            return mock_cat

        mgr.lazy_register_category("on_demand", loader)
        result = mgr.get_category("on_demand")

        assert loader_called == [1]
        assert result is mock_cat
        assert "on_demand" in mgr.categories

    def test_get_category_second_call_uses_cached(self, tmp_path):
        """GIVEN a lazy-registered category that was already loaded
        WHEN get_category is called a second time
        THEN the loader is NOT invoked again.
        """
        mgr = _mgr(tmp_path)

        mock_cat = Mock(spec=ToolCategory)
        mock_cat.description = ""
        mock_cat.path = tmp_path
        call_count = []

        def loader():
            call_count.append(1)
            return mock_cat

        mgr.lazy_register_category("once_only", loader)
        mgr.get_category("once_only")  # first access → loader called
        mgr.get_category("once_only")  # second access → from cache

        assert len(call_count) == 1

    def test_get_category_missing_returns_none(self, tmp_path):
        """GIVEN a manager with no such category
        WHEN get_category is called
        THEN None is returned.
        """
        mgr = _mgr(tmp_path)
        assert mgr.get_category("does_not_exist") is None


# ---------------------------------------------------------------------------
# Part 6 — list_categories include_count + list_tools/get_tool_schema errors
# ---------------------------------------------------------------------------

class TestManagerListAndSchemaHelpers:
    """Cover the list_tools error path and get_tool_schema helpers."""

    @pytest.mark.asyncio
    async def test_list_categories_include_count(self, tmp_path):
        """GIVEN a manager with one discovered category containing 2 tools
        WHEN list_categories(include_count=True) is called
        THEN the category entry includes tool_count.
        """
        mgr = _mgr(tmp_path)

        mock_cat = Mock(spec=ToolCategory)
        mock_cat.description = ""
        mock_cat.path = tmp_path
        mock_cat._discovered = True
        mock_cat._tools = {"t1": lambda: None, "t2": lambda: None}
        mgr.categories["counted_cat"] = mock_cat
        mgr._category_metadata["counted_cat"] = {"name": "counted_cat", "description": ""}

        result = await mgr.list_categories(include_count=True)
        entry = next((c for c in result if c["name"] == "counted_cat"), None)
        assert entry is not None
        assert "tool_count" in entry
        assert entry["tool_count"] == 2

    @pytest.mark.asyncio
    async def test_list_tools_missing_category(self, tmp_path):
        """GIVEN a manager with no such category
        WHEN list_tools is called
        THEN an error dict is returned.
        """
        mgr = _mgr(tmp_path)
        result = await mgr.list_tools("ghost_cat")
        assert result["status"] == "error"
        assert "ghost_cat" in result["error"]

    @pytest.mark.asyncio
    async def test_get_tool_schema_missing_category(self, tmp_path):
        """GIVEN a manager with no such category
        WHEN get_tool_schema is called
        THEN an error dict is returned.
        """
        mgr = _mgr(tmp_path)
        result = await mgr.get_tool_schema("ghost_cat", "some_tool")
        assert result["status"] == "error"
        assert "ghost_cat" in result["error"]

    @pytest.mark.asyncio
    async def test_get_tool_schema_missing_tool(self, tmp_path):
        """GIVEN a manager with a valid category but the tool does not exist
        WHEN get_tool_schema is called
        THEN an error dict is returned.
        """
        mgr = _mgr(tmp_path)
        mock_cat = Mock(spec=ToolCategory)
        mock_cat.get_tool_schema.return_value = None
        mgr.categories["valid_cat"] = mock_cat
        mgr._category_metadata["valid_cat"] = {"name": "valid_cat", "description": ""}

        result = await mgr.get_tool_schema("valid_cat", "ghost_tool")
        assert result["status"] == "error"
        assert "ghost_tool" in result["error"]

    @pytest.mark.asyncio
    async def test_get_tool_schema_success(self, tmp_path):
        """GIVEN a valid category and tool
        WHEN get_tool_schema is called
        THEN a dict with status=success and a schema is returned.
        """
        mgr = _mgr(tmp_path)
        mock_cat = Mock(spec=ToolCategory)
        mock_cat.get_tool_schema.return_value = {"name": "my_tool", "params": {}}
        mgr.categories["real_cat"] = mock_cat
        mgr._category_metadata["real_cat"] = {"name": "real_cat", "description": ""}

        result = await mgr.get_tool_schema("real_cat", "my_tool")
        assert result["status"] == "success"
        assert "schema" in result
        assert result["schema"]["name"] == "my_tool"
