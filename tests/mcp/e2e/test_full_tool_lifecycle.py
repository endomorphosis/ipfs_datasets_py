"""E2E tests for complete tool lifecycle workflows in MCP server."""

import pytest
from unittest.mock import Mock
from pathlib import Path


class TestToolLifecycle:
    """Test complete tool lifecycle workflows."""

    @pytest.mark.asyncio
    async def test_complete_tool_registration_flow(self):
        """Test complete tool registration and discovery flow."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock(name="test_cat", description="Test")
        mock_cat.list_tools = Mock(return_value=[{"name": "tool1", "description": "Tool 1"}])
        manager.categories = {"test_cat": mock_cat}
        manager._category_metadata = {"test_cat": {"name": "test_cat", "description": "Test"}}
        manager._discovered_categories = True
        
        categories = await manager.list_categories()
        tools_result = await manager.list_tools("test_cat")
        
        assert len(categories) > 0
        assert tools_result["status"] == "success"
        assert len(tools_result["tools"]) > 0

    @pytest.mark.asyncio
    async def test_tool_list_and_discovery(self):
        """Test tool listing across multiple categories."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat1 = Mock(name="cat1", description="Cat 1")
        mock_cat1.list_tools = Mock(return_value=[{"name": "t1", "description": "T1"}])
        mock_cat2 = Mock(name="cat2", description="Cat 2")
        mock_cat2.list_tools = Mock(return_value=[{"name": "t2", "description": "T2"}])
        manager.categories = {"cat1": mock_cat1, "cat2": mock_cat2}
        manager._discovered_categories = True
        
        cat1_tools = await manager.list_tools("cat1")
        cat2_tools = await manager.list_tools("cat2")
        
        assert cat1_tools["status"] == "success"
        assert len(cat1_tools["tools"]) == 1
        assert cat2_tools["status"] == "success"

    @pytest.mark.asyncio
    async def test_tool_execution_sync(self):
        """Test synchronous tool execution."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        def sync_tool(input_data: str) -> dict:
            return {"output": input_data.upper()}
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.get_tool = Mock(return_value=sync_tool)
        manager.categories = {"test_cat": mock_cat}
        manager._discovered_categories = True
        
        result = await manager.dispatch("test_cat", "sync_tool", {"input_data": "hello"})
        assert result["output"] == "HELLO"

    @pytest.mark.asyncio
    async def test_tool_execution_async(self):
        """Test asynchronous tool execution."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        import asyncio
        
        async def async_tool(input_data: str) -> dict:
            await asyncio.sleep(0.001)
            return {"output": input_data.lower()}
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.get_tool = Mock(return_value=async_tool)
        manager.categories = {"test_cat": mock_cat}
        manager._discovered_categories = True
        
        result = await manager.dispatch("test_cat", "async_tool", {"input_data": "WORLD"})
        assert result["output"] == "world"

    @pytest.mark.asyncio
    async def test_multi_tool_orchestration(self):
        """Test chaining multiple tools together."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        def tool1(data: str) -> dict:
            return {"processed": data.upper()}
        
        def tool2(data: str) -> dict:
            return {"result": f"Processed: {data}"}
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.get_tool = Mock(side_effect=lambda n: {"tool1": tool1, "tool2": tool2}.get(n))
        manager.categories = {"proc": mock_cat}
        manager._discovered_categories = True
        
        result1 = await manager.dispatch("proc", "tool1", {"data": "hello"})
        result2 = await manager.dispatch("proc", "tool2", {"data": result1["processed"]})
        
        assert result2["result"] == "Processed: HELLO"

    @pytest.mark.asyncio
    async def test_parameter_validation_end_to_end(self):
        """Test end-to-end parameter validation."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        def typed_tool(count: int, name: str) -> dict:
            return {"message": f"Hello {name} x{count}"}
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.get_tool = Mock(return_value=typed_tool)
        manager.categories = {"test": mock_cat}
        manager._discovered_categories = True
        
        result = await manager.dispatch("test", "typed_tool", {"count": 3, "name": "World"})
        assert "Hello World x3" in result["message"]

    @pytest.mark.asyncio
    async def test_schema_retrieval_workflow(self):
        """Test schema retrieval for tools."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_schema = {"name": "test_tool", "description": "Test", "parameters": {}}
        mock_cat = Mock()
        mock_cat.get_tool_schema = Mock(return_value=mock_schema)
        manager.categories = {"test": mock_cat}
        manager._discovered_categories = True
        
        schema_result = await manager.get_tool_schema("test", "test_tool")
        assert schema_result["status"] == "success"
        assert schema_result["schema"]["name"] == "test_tool"

    @pytest.mark.asyncio
    async def test_error_recovery_invalid_category(self):
        """Test error handling for invalid category."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        manager.categories = {}
        manager._discovered_categories = True
        
        result = await manager.dispatch("invalid", "tool", {})
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_error_recovery_invalid_tool(self):
        """Test error handling for invalid tool."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.get_tool = Mock(return_value=None)
        mock_cat.list_tools = Mock(return_value=[])
        manager.categories = {"test": mock_cat}
        manager._discovered_categories = True
        
        result = await manager.dispatch("test", "invalid", {})
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_state_persistence_across_operations(self):
        """Test that manager state persists across operations."""
        from ipfs_datasets_py.mcp_server import hierarchical_tool_manager
        
        manager = hierarchical_tool_manager.HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock(name="cat1", description="Cat")
        mock_cat.list_tools = Mock(return_value=[{"name": "t1", "description": "T1"}])
        manager.categories = {"cat1": mock_cat}
        manager._discovered_categories = True
        
        cats1 = await manager.list_categories()
        tools1 = await manager.list_tools("cat1")
        cats2 = await manager.list_categories()
        tools2 = await manager.list_tools("cat1")
        
        assert len(cats1) == len(cats2)
        assert tools1["status"] == tools2["status"]
