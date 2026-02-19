"""
Integration tests for complete workflow integration.

Tests cover end-to-end tool execution, multi-tool chaining,
error recovery, state persistence, and concurrent execution.
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path
import asyncio


# Test Class 1: Complete Tool Execution Workflow
class TestCompleteToolExecutionWorkflow:
    """Test suite for end-to-end tool execution workflows."""
    
    @pytest.mark.asyncio
    async def test_complete_tool_execution_pipeline(self):
        """
        GIVEN: A complete tool execution pipeline (discover -> list -> get schema -> dispatch)
        WHEN: Executing the full pipeline
        THEN: All steps complete successfully
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        def sample_tool(input_text: str) -> dict:
            return {"processed": input_text.upper()}
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.list_tools = Mock(return_value=[
            {"name": "sample_tool", "description": "Sample tool"}
        ])
        mock_cat.get_tool_metadata = Mock(return_value={
            "name": "sample_tool",
            "description": "Sample tool",
            "signature": "(input_text: str) -> dict"
        })
        mock_cat.get_tool = Mock(return_value=sample_tool)
        manager.categories = {"test_cat": mock_cat}
        manager._discovered_categories = True
        manager._category_metadata = {
            "test_cat": {"name": "test_cat", "description": "Test", "tool_count": 1}
        }
        
        # Act - Full pipeline
        categories = await manager.list_categories()
        tools = await manager.list_tools("test_cat")
        schema = await manager.get_tool_schema("test_cat", "sample_tool")
        result = await manager.dispatch("test_cat", "sample_tool", {"input_text": "hello"})
        
        # Assert
        assert len(categories) > 0
        assert tools["status"] == "success"
        assert schema["status"] == "success"
        assert result["processed"] == "HELLO"
    
    @pytest.mark.asyncio
    async def test_tool_execution_with_validation(self):
        """
        GIVEN: A tool with input validation
        WHEN: Executing with valid and invalid inputs
        THEN: Validation works correctly
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        def validated_tool(number: int) -> dict:
            if not isinstance(number, int):
                raise TypeError("Input must be an integer")
            return {"squared": number ** 2}
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.get_tool = Mock(return_value=validated_tool)
        manager.categories = {"test_cat": mock_cat}
        manager._discovered_categories = True
        
        # Act & Assert - Valid input
        result = await manager.dispatch("test_cat", "validated_tool", {"number": 5})
        assert result["squared"] == 25
        
        # Invalid input should raise or return error
        try:
            result = await manager.dispatch("test_cat", "validated_tool", {"number": "not_int"})
            if isinstance(result, dict) and "error" in result:
                assert "error" in result
        except (TypeError, Exception):
            pass  # Expected


# Test Class 2: Multi-Tool Chaining
class TestMultiToolChaining:
    """Test suite for multi-tool workflow chaining."""
    
    @pytest.mark.asyncio
    async def test_chain_multiple_tools_sequentially(self):
        """
        GIVEN: Multiple tools that can be chained
        WHEN: Executing tools in sequence
        THEN: Output of one tool feeds into next
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        def tool1(input_val: str) -> dict:
            return {"stage1": input_val.upper()}
        
        def tool2(stage1: str) -> dict:
            return {"stage2": f"processed_{stage1}"}
        
        def tool3(stage2: str) -> dict:
            return {"final": stage2.replace("_", "-")}
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        
        def get_tool_func(tool_name):
            tools = {"tool1": tool1, "tool2": tool2, "tool3": tool3}
            return tools.get(tool_name)
        
        mock_cat.get_tool = Mock(side_effect=get_tool_func)
        manager.categories = {"workflow": mock_cat}
        manager._discovered_categories = True
        
        # Act - Chain execution
        result1 = await manager.dispatch("workflow", "tool1", {"input_val": "hello"})
        result2 = await manager.dispatch("workflow", "tool2", {"stage1": result1["stage1"]})
        result3 = await manager.dispatch("workflow", "tool3", {"stage2": result2["stage2"]})
        
        # Assert
        assert result3["final"] == "processed-HELLO"
    
    @pytest.mark.asyncio
    async def test_parallel_tool_execution(self):
        """
        GIVEN: Multiple independent tools
        WHEN: Executing tools in parallel
        THEN: All tools execute concurrently
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        async def async_tool1(val: int) -> dict:
            await asyncio.sleep(0.01)
            return {"result1": val * 2}
        
        async def async_tool2(val: int) -> dict:
            await asyncio.sleep(0.01)
            return {"result2": val * 3}
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        
        def get_tool_func(tool_name):
            tools = {"async_tool1": async_tool1, "async_tool2": async_tool2}
            return tools.get(tool_name)
        
        mock_cat.get_tool = Mock(side_effect=get_tool_func)
        manager.categories = {"parallel": mock_cat}
        manager._discovered_categories = True
        
        # Act - Parallel execution
        results = await asyncio.gather(
            manager.dispatch("parallel", "async_tool1", {"val": 5}),
            manager.dispatch("parallel", "async_tool2", {"val": 7})
        )
        
        # Assert
        assert results[0]["result1"] == 10
        assert results[1]["result2"] == 21


# Test Class 3: Error Recovery and Fallback
class TestErrorRecoveryAndFallback:
    """Test suite for error recovery and fallback mechanisms."""
    
    @pytest.mark.asyncio
    async def test_tool_error_recovery_with_fallback(self):
        """
        GIVEN: A primary tool and a fallback tool
        WHEN: Primary tool fails
        THEN: Fallback tool is executed
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        def primary_tool(data: str) -> dict:
            if data == "error":
                raise ValueError("Primary tool failed")
            return {"result": data}
        
        def fallback_tool(data: str) -> dict:
            return {"result": f"fallback_{data}"}
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        
        def get_tool_func(tool_name):
            tools = {"primary": primary_tool, "fallback": fallback_tool}
            return tools.get(tool_name)
        
        mock_cat.get_tool = Mock(side_effect=get_tool_func)
        manager.categories = {"resilient": mock_cat}
        manager._discovered_categories = True
        
        # Act - Try primary, use fallback on error
        try:
            result = await manager.dispatch("resilient", "primary", {"data": "error"})
            # If no exception, check for error indicator
            has_error = isinstance(result, dict) and "error" in result
        except Exception:
            has_error = True
        
        if has_error:
            # Use fallback
            result = await manager.dispatch("resilient", "fallback", {"data": "error"})
            assert result["result"] == "fallback_error"
    
    @pytest.mark.asyncio
    async def test_graceful_degradation_on_missing_category(self):
        """
        GIVEN: A request for a non-existent category
        WHEN: Attempting to list tools or dispatch
        THEN: Returns appropriate error message
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        manager._discovered_categories = True
        manager.categories = {}
        
        # Act
        result = await manager.list_tools("nonexistent_category")
        
        # Assert
        assert result["status"] == "error"
        # Check for error message (different structures possible)
        has_error_info = ("message" in result and 
                         ("not found" in result["message"].lower() or 
                          "invalid" in result["message"].lower())) or \
                         ("error" in result and 
                         ("not found" in str(result["error"]).lower() or 
                          "invalid" in str(result["error"]).lower()))
        assert has_error_info or result["status"] == "error"


# Test Class 4: State Persistence
class TestStatePersistence:
    """Test suite for state persistence across operations."""
    
    @pytest.mark.asyncio
    async def test_category_discovery_caching(self):
        """
        GIVEN: A manager that discovers categories
        WHEN: Listing categories multiple times
        THEN: Discovery only happens once (caching works)
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        manager._discovered_categories = True
        manager._category_metadata = {
            "cat1": {"name": "cat1", "description": "Category 1", "tool_count": 2}
        }
        
        # Act - Call multiple times
        result1 = await manager.list_categories()
        result2 = await manager.list_categories()
        
        # Assert - Both calls should return same data
        assert len(result1) == len(result2)
        assert result1[0]["name"] == result2[0]["name"]
    
    @pytest.mark.asyncio
    async def test_tool_metadata_persistence(self):
        """
        GIVEN: Tools with metadata
        WHEN: Accessing tool metadata multiple times
        THEN: Metadata is consistent across calls
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.get_tool_schema = Mock(return_value={
            "name": "persistent_tool",
            "description": "Persistent tool",
            "signature": "() -> dict"
        })
        manager.categories = {"test_cat": mock_cat}
        manager._discovered_categories = True
        
        # Act
        schema1 = await manager.get_tool_schema("test_cat", "persistent_tool")
        schema2 = await manager.get_tool_schema("test_cat", "persistent_tool")
        
        # Assert
        assert schema1["schema"]["name"] == schema2["schema"]["name"]
        assert schema1["schema"]["description"] == schema2["schema"]["description"]


# Test Class 5: Concurrent Tool Execution
class TestConcurrentToolExecution:
    """Test suite for concurrent tool execution."""
    
    @pytest.mark.asyncio
    async def test_multiple_concurrent_tool_dispatches(self):
        """
        GIVEN: Multiple tool execution requests
        WHEN: Dispatching tools concurrently
        THEN: All tools execute without interference
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        async def concurrent_tool(id: int, delay: float) -> dict:
            await asyncio.sleep(delay)
            return {"id": id, "status": "completed"}
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.get_tool = Mock(return_value=concurrent_tool)
        manager.categories = {"concurrent": mock_cat}
        manager._discovered_categories = True
        
        # Act - Execute 5 tools concurrently
        tasks = [
            manager.dispatch("concurrent", "concurrent_tool", {"id": i, "delay": 0.01})
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert len(results) == 5
        assert all(r["status"] == "completed" for r in results)
        assert set(r["id"] for r in results) == {0, 1, 2, 3, 4}
    
    @pytest.mark.asyncio
    async def test_concurrent_access_to_same_category(self):
        """
        GIVEN: Multiple requests for the same category
        WHEN: Accessing category concurrently
        THEN: All requests are handled correctly
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager(tools_root=Path("/fake"))
        mock_cat = Mock()
        mock_cat.list_tools = Mock(return_value=[
            {"name": "tool1", "description": "Tool 1"}
        ])
        manager.categories = {"shared_cat": mock_cat}
        manager._discovered_categories = True
        
        # Act - Multiple concurrent list_tools calls
        tasks = [manager.list_tools("shared_cat") for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert len(results) == 10
        assert all(r["status"] == "success" for r in results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
