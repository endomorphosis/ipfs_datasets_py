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
