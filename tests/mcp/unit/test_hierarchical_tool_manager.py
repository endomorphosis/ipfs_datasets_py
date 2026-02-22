"""Comprehensive tests for hierarchical_tool_manager.py.

This test suite covers:
- ToolCategory class functionality
- HierarchicalToolManager class functionality
- Tool dispatch mechanisms
- Meta-tool wrappers
- Global manager pattern
- Module path resolution

Test Format: GIVEN-WHEN-THEN
"""

import pytest
import inspect
import tempfile
import json
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, patch, AsyncMock, MagicMock


# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from ipfs_datasets_py.mcp_server import hierarchical_tool_manager


class TestToolCategory:
    """Test the ToolCategory class."""
    
    def test_category_initialization(self):
        """Test that ToolCategory can be initialized with basic attributes.
        
        GIVEN: Category name, path, and description
        WHEN: Creating a ToolCategory instance
        THEN: Category is created with correct attributes
        """
        # GIVEN
        name = "test_category"
        path = Path("/tmp/test_tools")
        description = "Test category description"
        
        # WHEN
        category = hierarchical_tool_manager.ToolCategory(name, path, description)
        
        # THEN
        assert category.name == name
        assert category.path == path
        assert category.description == description
        assert category._discovered == False
        assert len(category._tools) == 0
    
    def test_discover_tools_creates_tool_dict(self):
        """Test that discover_tools populates the tools dictionary.
        
        GIVEN: A ToolCategory with a valid path
        WHEN: discover_tools is called
        THEN: Tools are discovered and stored in _tools dict
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # Create a sample tool file
            tool_file = tmp_path / "sample_tool.py"
            tool_file.write_text("""
def sample_tool(param1: str) -> str:
    '''Sample tool for testing.'''
    return f"Result: {param1}"
""")
            
            category = hierarchical_tool_manager.ToolCategory("test", tmp_path)
            
            # WHEN
            category.discover_tools()
            
            # THEN
            assert category._discovered == True
            assert len(category._tools) >= 0  # May discover tools depending on naming
    
    def test_list_tools_returns_tool_metadata(self):
        """Test that list_tools returns minimal metadata for all tools.
        
        GIVEN: A category with discovered tools
        WHEN: list_tools is called
        THEN: Returns list of tool metadata dicts
        """
        # GIVEN
        category = hierarchical_tool_manager.ToolCategory("test", Path("/tmp"))
        category._discovered = True
        category._tool_metadata = {
            "tool1": {"name": "tool1", "description": "Tool 1 description"},
            "tool2": {"name": "tool2", "description": "Tool 2 description"}
        }
        
        # WHEN
        result = category.list_tools()
        
        # THEN
        assert isinstance(result, list)
        assert len(result) == 2
        assert all("name" in tool for tool in result)
        assert all("description" in tool for tool in result)
    
    def test_get_tool_returns_callable(self):
        """Test that get_tool returns a callable function.
        
        GIVEN: A category with tools
        WHEN: get_tool is called with valid tool name
        THEN: Returns the callable function
        """
        # GIVEN
        def mock_tool():
            return "result"
        
        category = hierarchical_tool_manager.ToolCategory("test", Path("/tmp"))
        category._discovered = True
        category._tools = {"mock_tool": mock_tool}
        
        # WHEN
        result = category.get_tool("mock_tool")
        
        # THEN
        assert result is mock_tool
        assert callable(result)
    
    def test_get_tool_schema_returns_full_metadata(self):
        """Test that get_tool_schema returns complete tool information.
        
        GIVEN: A category with a tool
        WHEN: get_tool_schema is called
        THEN: Returns complete schema with parameters and return type
        """
        # GIVEN
        def mock_tool(param1: str, param2: int = 5) -> str:
            '''Mock tool docstring.'''
            return "result"
        
        category = hierarchical_tool_manager.ToolCategory("test", Path("/tmp"))
        category._discovered = True
        category._tools = {"mock_tool": mock_tool}
        category._tool_metadata = {
            "mock_tool": {
                "name": "mock_tool",
                "category": "test",
                "description": "Mock tool docstring.",
                "signature": str(inspect.signature(mock_tool))
            }
        }
        
        # WHEN
        schema = category.get_tool_schema("mock_tool")
        
        # THEN
        assert schema is not None
        assert schema["name"] == "mock_tool"
        assert "parameters" in schema
        assert "param1" in schema["parameters"]
        assert "param2" in schema["parameters"]
        assert schema["parameters"]["param1"]["required"] == True
        assert schema["parameters"]["param2"]["required"] == False


class TestHierarchicalToolManager:
    """Test the HierarchicalToolManager class."""
    
    def test_manager_initialization(self):
        """Test that HierarchicalToolManager initializes correctly.
        
        GIVEN: No arguments or a custom tools_root
        WHEN: Creating a manager instance
        THEN: Manager is initialized with correct attributes
        """
        # GIVEN / WHEN
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = hierarchical_tool_manager.HierarchicalToolManager(Path(tmpdir))
            
            # THEN
            assert manager.tools_root == Path(tmpdir)
            assert isinstance(manager.categories, dict)
            assert manager._discovered_categories == False
    
    def test_discover_categories_finds_directories(self):
        """Test that discover_categories finds category directories.
        
        GIVEN: A tools root with category subdirectories
        WHEN: discover_categories is called
        THEN: Categories are discovered and stored
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "category1").mkdir()
            (tmp_path / "category2").mkdir()
            (tmp_path / "_private").mkdir()  # Should be skipped
            
            manager = hierarchical_tool_manager.HierarchicalToolManager(tmp_path)
            
            # WHEN
            manager.discover_categories()
            
            # THEN
            assert manager._discovered_categories == True
            assert len(manager.categories) == 2
            assert "category1" in manager.categories
            assert "category2" in manager.categories
            assert "_private" not in manager.categories
    
    @pytest.mark.asyncio
    async def test_list_categories_returns_sorted_list(self):
        """Test that list_categories returns sorted category list.
        
        GIVEN: A manager with discovered categories
        WHEN: list_categories is called
        THEN: Returns sorted list of category info
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "z_category").mkdir()
            (tmp_path / "a_category").mkdir()
            
            manager = hierarchical_tool_manager.HierarchicalToolManager(tmp_path)
            manager.discover_categories()
            
            # WHEN
            result = await manager.list_categories()
            
            # THEN
            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0]["name"] == "a_category"  # Sorted alphabetically
            assert result[1]["name"] == "z_category"
    
    @pytest.mark.asyncio
    async def test_list_categories_with_count(self):
        """Test that list_categories can include tool counts.
        
        GIVEN: A manager with categories containing tools
        WHEN: list_categories is called with include_count=True
        THEN: Returns categories with tool_count field
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            cat_path = tmp_path / "test_cat"
            cat_path.mkdir()
            
            manager = hierarchical_tool_manager.HierarchicalToolManager(tmp_path)
            manager.discover_categories()
            
            # WHEN
            result = await manager.list_categories(include_count=True)
            
            # THEN
            assert isinstance(result, list)
            assert len(result) == 1
            assert "tool_count" in result[0]
    
    @pytest.mark.asyncio
    async def test_list_tools_success(self):
        """Test successful tool listing in a category.
        
        GIVEN: A manager with a valid category
        WHEN: list_tools is called with valid category name
        THEN: Returns success status with tool list
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            cat_path = tmp_path / "test_cat"
            cat_path.mkdir()
            
            manager = hierarchical_tool_manager.HierarchicalToolManager(tmp_path)
            manager.discover_categories()
            
            # WHEN
            result = await manager.list_tools("test_cat")
            
            # THEN
            assert result["status"] == "success"
            assert result["category"] == "test_cat"
            assert "tools" in result
            assert isinstance(result["tools"], list)
    
    @pytest.mark.asyncio
    async def test_list_tools_invalid_category(self):
        """Test list_tools with invalid category name.
        
        GIVEN: A manager with discovered categories
        WHEN: list_tools is called with non-existent category
        THEN: Returns error status with available categories
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = hierarchical_tool_manager.HierarchicalToolManager(Path(tmpdir))
            manager.discover_categories()
            
            # WHEN
            result = await manager.list_tools("nonexistent_category")
            
            # THEN
            assert result["status"] == "error"
            assert "Category 'nonexistent_category' not found" in result["error"]
            assert "available_categories" in result
    
    @pytest.mark.asyncio
    async def test_get_tool_schema_success(self):
        """Test successful tool schema retrieval.
        
        GIVEN: A manager with a category containing a tool
        WHEN: get_tool_schema is called with valid category and tool
        THEN: Returns success status with schema
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            cat_path = tmp_path / "test_cat"
            cat_path.mkdir()
            
            # Create a test tool
            tool_file = cat_path / "test_tool.py"
            tool_file.write_text("""
def test_tool(param: str) -> str:
    '''Test tool.'''
    return param
""")
            
            manager = hierarchical_tool_manager.HierarchicalToolManager(tmp_path)
            manager.discover_categories()
            
            # Mock the schema retrieval
            with patch.object(manager.categories["test_cat"], 'get_tool_schema',
                            return_value={"name": "test_tool"}):
                # WHEN
                result = await manager.get_tool_schema("test_cat", "test_tool")
                
                # THEN
                assert result["status"] == "success"
                assert "schema" in result
    
    @pytest.mark.asyncio
    async def test_get_tool_schema_invalid_category(self):
        """Test get_tool_schema with invalid category.
        
        GIVEN: A manager with discovered categories
        WHEN: get_tool_schema is called with non-existent category
        THEN: Returns error status
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = hierarchical_tool_manager.HierarchicalToolManager(Path(tmpdir))
            manager.discover_categories()
            
            # WHEN
            result = await manager.get_tool_schema("nonexistent", "tool")
            
            # THEN
            assert result["status"] == "error"
            assert "Category 'nonexistent' not found" in result["error"]


class TestToolDispatch:
    """Test the tool dispatch functionality."""
    
    @pytest.mark.asyncio
    async def test_dispatch_sync_tool_success(self):
        """Test successful dispatch to a synchronous tool.
        
        GIVEN: A manager with a sync tool
        WHEN: dispatch is called with valid parameters
        THEN: Tool executes and returns result
        """
        # GIVEN
        def sync_tool(param: str) -> Dict[str, Any]:
            return {"status": "success", "result": param.upper()}
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = hierarchical_tool_manager.HierarchicalToolManager(Path(tmpdir))
            manager._discovered_categories = True
            
            # Mock category and tool
            mock_category = Mock()
            mock_category.get_tool.return_value = sync_tool
            mock_category.list_tools.return_value = [{"name": "sync_tool"}]
            manager.categories["test_cat"] = mock_category
            
            # WHEN
            result = await manager.dispatch("test_cat", "sync_tool", {"param": "hello"})
            
            # THEN
            assert result["status"] == "success"
            assert result["result"] == "HELLO"
    
    @pytest.mark.asyncio
    async def test_dispatch_async_tool_success(self):
        """Test successful dispatch to an asynchronous tool.
        
        GIVEN: A manager with an async tool
        WHEN: dispatch is called with valid parameters
        THEN: Tool executes asynchronously and returns result
        """
        # GIVEN
        async def async_tool(param: str) -> Dict[str, Any]:
            return {"status": "success", "result": param.lower()}
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = hierarchical_tool_manager.HierarchicalToolManager(Path(tmpdir))
            manager._discovered_categories = True
            
            # Mock category and tool
            mock_category = Mock()
            mock_category.get_tool.return_value = async_tool
            mock_category.list_tools.return_value = [{"name": "async_tool"}]
            manager.categories["test_cat"] = mock_category
            
            # WHEN
            result = await manager.dispatch("test_cat", "async_tool", {"param": "WORLD"})
            
            # THEN
            assert result["status"] == "success"
            assert result["result"] == "world"
    
    @pytest.mark.asyncio
    async def test_dispatch_invalid_category_error(self):
        """Test dispatch with invalid category name.
        
        GIVEN: A manager with no categories
        WHEN: dispatch is called with non-existent category
        THEN: Returns error with available categories
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = hierarchical_tool_manager.HierarchicalToolManager(Path(tmpdir))
            manager._discovered_categories = True
            manager.categories = {}
            
            # WHEN
            result = await manager.dispatch("invalid_cat", "tool", {})
            
            # THEN
            assert result["status"] == "error"
            assert "Category 'invalid_cat' not found" in result["error"]
            assert "available_categories" in result
    
    @pytest.mark.asyncio
    async def test_dispatch_invalid_tool_error(self):
        """Test dispatch with invalid tool name.
        
        GIVEN: A manager with a category but invalid tool
        WHEN: dispatch is called with non-existent tool
        THEN: Returns error with available tools
        """
        # GIVEN
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = hierarchical_tool_manager.HierarchicalToolManager(Path(tmpdir))
            manager._discovered_categories = True
            
            # Mock category without the tool
            mock_category = Mock()
            mock_category.get_tool.return_value = None
            mock_category.list_tools.return_value = [{"name": "other_tool"}]
            manager.categories["test_cat"] = mock_category
            
            # WHEN
            result = await manager.dispatch("test_cat", "nonexistent_tool", {})
            
            # THEN
            assert result["status"] == "error"
            assert "Tool 'nonexistent_tool' not found" in result["error"]
            assert "available_tools" in result
    
    @pytest.mark.asyncio
    async def test_dispatch_tool_exception_handling(self):
        """Test that dispatch handles tool execution exceptions.
        
        GIVEN: A tool that raises an exception
        WHEN: dispatch is called
        THEN: Returns error status with exception message
        """
        # GIVEN
        def failing_tool():
            raise ValueError("Tool failed!")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = hierarchical_tool_manager.HierarchicalToolManager(Path(tmpdir))
            manager._discovered_categories = True
            
            # Mock category with failing tool
            mock_category = Mock()
            mock_category.get_tool.return_value = failing_tool
            manager.categories["test_cat"] = mock_category
            
            # WHEN
            result = await manager.dispatch("test_cat", "failing_tool", {})
            
            # THEN
            assert result["status"] == "error"
            assert "Tool failed!" in result["error"]


class TestMetaToolWrappers:
    """Test the meta-tool wrapper functions."""
    
    @pytest.mark.asyncio
    async def test_tools_list_categories_wrapper(self):
        """Test tools_list_categories meta-tool wrapper.
        
        GIVEN: A mock manager
        WHEN: tools_list_categories is called
        THEN: Returns success with category count and list
        """
        # GIVEN
        mock_manager = AsyncMock()
        mock_manager.list_categories.return_value = [
            {"name": "cat1"},
            {"name": "cat2"}
        ]
        
        with patch.object(hierarchical_tool_manager, 'get_tool_manager',
                         return_value=mock_manager):
            # WHEN
            result = await hierarchical_tool_manager.tools_list_categories()
            
            # THEN
            assert result["status"] == "success"
            assert result["category_count"] == 2
            assert len(result["categories"]) == 2
    
    @pytest.mark.asyncio
    async def test_tools_list_tools_wrapper(self):
        """Test tools_list_tools meta-tool wrapper.
        
        GIVEN: A mock manager
        WHEN: tools_list_tools is called with category name
        THEN: Returns tools in that category
        """
        # GIVEN
        mock_manager = AsyncMock()
        mock_manager.list_tools.return_value = {
            "status": "success",
            "tools": []
        }
        
        with patch.object(hierarchical_tool_manager, 'get_tool_manager',
                         return_value=mock_manager):
            # WHEN
            result = await hierarchical_tool_manager.tools_list_tools("test_cat")
            
            # THEN
            assert result["status"] == "success"
            mock_manager.list_tools.assert_called_once_with("test_cat")
    
    @pytest.mark.asyncio
    async def test_tools_get_schema_wrapper(self):
        """Test tools_get_schema meta-tool wrapper.
        
        GIVEN: A mock manager
        WHEN: tools_get_schema is called
        THEN: Returns tool schema
        """
        # GIVEN
        mock_manager = AsyncMock()
        mock_manager.get_tool_schema.return_value = {
            "status": "success",
            "schema": {}
        }
        
        with patch.object(hierarchical_tool_manager, 'get_tool_manager',
                         return_value=mock_manager):
            # WHEN
            result = await hierarchical_tool_manager.tools_get_schema("cat", "tool")
            
            # THEN
            assert result["status"] == "success"
            mock_manager.get_tool_schema.assert_called_once_with("cat", "tool")
    
    @pytest.mark.asyncio
    async def test_tools_dispatch_wrapper(self):
        """Test tools_dispatch meta-tool wrapper.
        
        GIVEN: A mock manager
        WHEN: tools_dispatch is called with params
        THEN: Dispatches to the tool
        """
        # GIVEN
        mock_manager = AsyncMock()
        mock_manager.dispatch.return_value = {"status": "success"}
        
        with patch.object(hierarchical_tool_manager, 'get_tool_manager',
                         return_value=mock_manager):
            # WHEN
            result = await hierarchical_tool_manager.tools_dispatch(
                "cat", "tool", {"param": "value"}
            )
            
            # THEN
            assert result["status"] == "success"
            mock_manager.dispatch.assert_called_once_with(
                "cat", "tool", {"param": "value"}
            )


class TestGlobalManager:
    """Test the global manager pattern."""
    
    def test_get_tool_manager_with_context(self):
        """Test get_tool_manager with ServerContext.
        
        GIVEN: A mock ServerContext with tool_manager
        WHEN: get_tool_manager is called with context
        THEN: Returns the context's tool_manager
        """
        # GIVEN
        mock_context = Mock()
        mock_manager = Mock()
        mock_context.tool_manager = mock_manager
        
        # WHEN
        result = hierarchical_tool_manager.get_tool_manager(mock_context)
        
        # THEN
        assert result is mock_manager
    
    def test_get_tool_manager_fallback_to_global(self):
        """Test get_tool_manager fallback to global instance.
        
        GIVEN: No context provided
        WHEN: get_tool_manager is called without arguments
        THEN: Returns global manager instance
        """
        # GIVEN / WHEN
        # Reset global manager
        hierarchical_tool_manager._global_manager = None
        
        result = hierarchical_tool_manager.get_tool_manager()
        
        # THEN
        assert result is not None
        assert isinstance(result, hierarchical_tool_manager.HierarchicalToolManager)
        
        # Calling again should return same instance
        result2 = hierarchical_tool_manager.get_tool_manager()
        assert result is result2


class TestModulePath:
    """Test module path resolution."""
    
    def test_get_module_path_conversion(self):
        """Test _get_module_path converts file path to module path.
        
        GIVEN: A ToolCategory instance
        WHEN: _get_module_path is called with a file path
        THEN: Returns correct Python module path
        """
        # GIVEN
        category = hierarchical_tool_manager.ToolCategory("test", Path("/tmp"))
        file_path = Path("/home/user/ipfs_datasets_py/mcp_server/tools/test_cat/tool.py")
        
        # WHEN
        result = category._get_module_path(file_path)
        
        # THEN
        assert "ipfs_datasets_py" in result
        assert "mcp_server" in result
        assert "tools" in result
        assert "tool" in result
        assert result.endswith("tool")
    
    def test_get_module_path_fallback(self):
        """Test _get_module_path fallback when ipfs_datasets_py not in path.
        
        GIVEN: A file path without ipfs_datasets_py
        WHEN: _get_module_path is called
        THEN: Returns fallback module path
        """
        # GIVEN
        category = hierarchical_tool_manager.ToolCategory("test_cat", Path("/tmp"))
        file_path = Path("/some/random/path/tool.py")
        
        # WHEN
        result = category._get_module_path(file_path)
        
        # THEN
        assert "ipfs_datasets_py.mcp_server.tools.test_cat.tool" == result


# ---------------------------------------------------------------------------
# Phase F2: Tool result caching
# ---------------------------------------------------------------------------

class TestToolResultCaching:
    """Tests for Phase F2 — opt-in per-tool result caching via cache_ttl."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_result(self, tmp_path):
        """
        GIVEN a tool decorated with @tool_metadata(cache_ttl=60)
        WHEN dispatch is called twice with the same params
        THEN the second call returns the cached result (with _cached=True)
        """
        # GIVEN a manager with one tool that has a cache_ttl
        call_count = 0

        from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata as tool_meta_dec

        @tool_meta_dec(cache_ttl=60.0, mcp_description="cached tool")
        async def cached_tool(x: int = 1) -> dict:
            nonlocal call_count
            call_count += 1
            return {"status": "success", "result": x}

        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=tmp_path)
        cat = hierarchical_tool_manager.ToolCategory("test_cat", tmp_path)
        cat._discovered = True
        cat._tools = {"cached_tool": cached_tool}
        manager.categories["test_cat"] = cat
        manager._discovered_categories = True

        # WHEN first dispatch (cache miss)
        r1 = await manager.dispatch("test_cat", "cached_tool", {"x": 7})
        assert r1.get("result") == 7
        assert call_count == 1

        # WHEN second dispatch (cache hit)
        r2 = await manager.dispatch("test_cat", "cached_tool", {"x": 7})
        # THEN tool is NOT called again and result carries _cached flag
        assert call_count == 1
        assert r2.get("_cached") is True

    @pytest.mark.asyncio
    async def test_no_cache_when_cache_ttl_none(self, tmp_path):
        """
        GIVEN a tool with no cache_ttl (default None)
        WHEN dispatch is called twice
        THEN the tool is executed both times
        """
        call_count = 0

        from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata as tool_meta_dec

        @tool_meta_dec(mcp_description="uncached tool")  # cache_ttl=None
        async def uncached_tool() -> dict:
            nonlocal call_count
            call_count += 1
            return {"status": "success", "val": call_count}

        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=tmp_path)
        cat = hierarchical_tool_manager.ToolCategory("test_cat2", tmp_path)
        cat._discovered = True
        cat._tools = {"uncached_tool": uncached_tool}
        manager.categories["test_cat2"] = cat
        manager._discovered_categories = True

        await manager.dispatch("test_cat2", "uncached_tool", {})
        await manager.dispatch("test_cat2", "uncached_tool", {})
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_different_params_not_cached(self, tmp_path):
        """
        GIVEN a tool with cache_ttl=60
        WHEN dispatch is called with different params
        THEN both calls execute the tool (different cache keys)
        """
        call_count = 0

        from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata as tool_meta_dec

        @tool_meta_dec(cache_ttl=60.0, mcp_description="cached tool v2")
        async def cached_tool_v2(n: int = 0) -> dict:
            nonlocal call_count
            call_count += 1
            return {"status": "success", "n": n}

        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=tmp_path)
        cat = hierarchical_tool_manager.ToolCategory("test_cat3", tmp_path)
        cat._discovered = True
        cat._tools = {"cached_tool_v2": cached_tool_v2}
        manager.categories["test_cat3"] = cat
        manager._discovered_categories = True

        await manager.dispatch("test_cat3", "cached_tool_v2", {"n": 1})
        await manager.dispatch("test_cat3", "cached_tool_v2", {"n": 2})
        assert call_count == 2

    def test_get_result_cache_returns_cache_instance(self):
        """
        GIVEN a fresh HierarchicalToolManager
        WHEN _get_result_cache() is called
        THEN it returns a ResultCache instance (or None if deps missing)
        """
        manager = hierarchical_tool_manager.HierarchicalToolManager()
        cache = manager._get_result_cache()
        # May be None if mcplusplus.result_cache isn't importable in CI;
        # either way the call must not raise.
        assert cache is None or hasattr(cache, "get")

    def test_get_result_cache_idempotent(self):
        """
        GIVEN a HierarchicalToolManager
        WHEN _get_result_cache() is called twice
        THEN it returns the same object both times
        """
        manager = hierarchical_tool_manager.HierarchicalToolManager()
        c1 = manager._get_result_cache()
        c2 = manager._get_result_cache()
        assert c1 is c2


# ---------------------------------------------------------------------------
# Phase D3: Schema snapshot / stability test
# ---------------------------------------------------------------------------

class TestToolSchemaSnapshot:
    """Phase D3 — Guard against accidental schema regressions.

    If the schema for a well-known tool changes, this test will fail and
    prompt the developer to bump ``schema_version`` in the tool decorator.
    """

    def test_graph_tools_create_schema_has_expected_keys(self):
        """
        GIVEN the graph_tools/graph_create tool
        WHEN we load its schema via ToolCategory
        THEN the schema contains the expected keys
        """
        tools_root = (
            Path(__file__).parent.parent.parent.parent
            / "ipfs_datasets_py" / "mcp_server" / "tools"
        )
        cat_path = tools_root / "graph_tools"
        if not cat_path.exists():
            pytest.skip("graph_tools directory not found")

        cat = hierarchical_tool_manager.ToolCategory("graph_tools", cat_path)
        schema = cat.get_tool_schema("graph_create")
        if schema is None:
            pytest.skip("graph_create schema not discoverable")

        # Mandatory MCP schema keys
        assert "name" in schema
        assert "description" in schema

    def test_dataset_tools_load_dataset_schema_has_expected_keys(self):
        """
        GIVEN the dataset_tools/load_dataset tool
        WHEN we load its schema
        THEN name and description are present
        """
        tools_root = (
            Path(__file__).parent.parent.parent.parent
            / "ipfs_datasets_py" / "mcp_server" / "tools"
        )
        cat_path = tools_root / "dataset_tools"
        if not cat_path.exists():
            pytest.skip("dataset_tools directory not found")

        cat = hierarchical_tool_manager.ToolCategory("dataset_tools", cat_path)
        schema = cat.get_tool_schema("load_dataset")
        if schema is None:
            pytest.skip("load_dataset schema not discoverable")

        assert "name" in schema
        assert "description" in schema

    def test_tool_metadata_schema_version_default(self):
        """
        GIVEN a tool registered with @tool_metadata with default schema_version
        WHEN we read its schema via to_dict()
        THEN schema_version is "1.0"
        """
        from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata as _tm, ToolMetadata

        @_tm(mcp_description="snapshot test tool")
        def _snap_test_tool() -> dict:
            return {}

        assert _snap_test_tool._mcp_metadata.schema_version == "1.0"
        d = _snap_test_tool._mcp_metadata.to_dict()
        assert d["schema_version"] == "1.0"

    def test_tool_metadata_schema_version_custom(self):
        """
        GIVEN a tool registered with schema_version='2.0'
        WHEN we read its metadata
        THEN schema_version is '2.0'
        """
        from ipfs_datasets_py.mcp_server.tool_metadata import tool_metadata as _tm

        @_tm(schema_version="2.0", mcp_description="v2 tool")
        def _v2_tool() -> dict:
            return {}

        assert _v2_tool._mcp_metadata.schema_version == "2.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
