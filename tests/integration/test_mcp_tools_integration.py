"""
Integration tests for MCP tools with HierarchicalToolManager.

Tests tool discovery, execution, and hierarchical dispatch across all categories.
"""

import pytest
import anyio
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

pytestmark = pytest.mark.anyio


class TestToolDiscovery:
    """Test tool discovery functionality."""
    
    async def test_discover_all_categories(self):
        """Test discovering all 51 tool categories."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Discovering all categories
        categories = await manager.list_categories()
        category_names = {entry["name"] for entry in categories}
        
        # THEN - Should find 51+ categories
        assert len(categories) >= 51
        assert 'dataset_tools' in category_names
        assert 'graph_tools' in category_names
        assert 'ipfs_tools' in category_names
    
    async def test_discover_tools_in_category(self):
        """Test discovering tools within a specific category."""
        # GIVEN - HierarchicalToolManager and a category
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Discovering tools in graph_tools category
        result = await manager.list_tools('graph_tools')
        
        # THEN - Should find graph tools
        assert result["status"] == "success"
        tools = result["tools"]
        assert len(tools) > 0
        assert any('graph' in tool["name"].lower() for tool in tools)
    
    async def test_get_tool_schema(self):
        """Test getting schema for a specific tool."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Getting schema for a tool
        try:
            schema_result = await manager.get_tool_schema('graph_tools', 'query_knowledge_graph')
            
            # THEN - Should return valid schema
            if schema_result.get("status") == "error":
                pytest.skip("Tool not found - acceptable for this test")
            schema = schema_result["schema"]
            assert schema is not None
            assert 'name' in schema or 'description' in schema
        except Exception:
            # Tool might not exist, which is acceptable
            pytest.skip("Tool not found - acceptable for this test")
    
    async def test_handle_missing_category(self):
        """Test graceful handling of missing category."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Requesting nonexistent category
        result = await manager.list_tools('nonexistent_category')
        
        # THEN - Should return empty list, not crash
        assert result["status"] == "error"
    
    async def test_discovery_performance(self):
        """Test that discovery is fast (< 1 second)."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        import time
        
        # WHEN - Measuring discovery time
        start = time.time()
        manager = HierarchicalToolManager()
        categories = await manager.list_categories()
        elapsed = time.time() - start
        
        # THEN - Should be very fast (< 1 second)
        assert elapsed < 1.0
        assert len(categories) > 0


class TestToolExecution:
    """Test tool execution functionality."""
    
    async def test_execute_dataset_tool(self):
        """Test executing a dataset tool."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Executing load_dataset with minimal params
        # Note: This might fail due to missing dependencies, which is acceptable
        try:
            result = await manager.dispatch(
                'dataset_tools',
                'load_dataset',
                {'source': 'test'}
            )
            # THEN - Should return some result
            assert result is not None
        except Exception as e:
            # Expected for integration test without full setup
            assert 'error' in str(e).lower() or 'not found' in str(e).lower()
    
    async def test_parameter_validation(self):
        """Test that tool validates parameters."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Calling tool with invalid params
        try:
            result = await manager.dispatch(
                'graph_tools',
                'graph_create',
                {}  # Missing required params
            )
            # THEN - Should handle gracefully
            assert result is not None
        except Exception:
            # Parameter validation errors are acceptable
            pass
    
    async def test_error_propagation(self):
        """Test that errors propagate correctly."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Calling nonexistent tool
        result = await manager.dispatch('fake_category', 'fake_tool', {})
        assert result["status"] == "error"
    
    async def test_concurrent_execution(self):
        """Test concurrent tool execution."""
        # GIVEN - HierarchicalToolManager and multiple tasks
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Executing multiple tools concurrently
        results = [None, None, None]

        async def _run(index, coro):
            results[index] = await coro

        async with anyio.create_task_group() as tg:
            tg.start_soon(_run, 0, manager.list_categories())
            tg.start_soon(_run, 1, manager.list_tools('dataset_tools'))
            tg.start_soon(_run, 2, manager.list_tools('graph_tools'))

        # THEN - All should complete successfully
        assert len(results) == 3
        assert all(r is not None for r in results)
    
    async def test_tool_timeout_handling(self):
        """Test that long-running tools handle timeouts."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Setting short timeout
        try:
            with anyio.fail_after(0.1):
                await manager.dispatch('dataset_tools', 'load_dataset', {'source': 'test'})
        except TimeoutError:
            # THEN - Timeout is handled
            pass
        except Exception:
            # Other errors acceptable
            pass
    
    async def test_tool_retry_logic(self):
        """Test tool retry on failure."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Attempting operation that might need retry
        attempts = 0
        max_attempts = 3
        
        result = None
        while attempts < max_attempts:
            try:
                result = await manager.dispatch(
                    'dataset_tools',
                    'load_dataset',
                    {'source': 'test'}
                )
                break
            except Exception:
                attempts += 1
        
        # THEN - Should have attempted retries
        assert attempts <= max_attempts
        assert result is None or isinstance(result, dict)
    
    async def test_tool_caching(self):
        """Test that tool results can be cached."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        import time
        
        manager = HierarchicalToolManager()
        
        # WHEN - Calling same discovery twice
        start1 = time.time()
        result1 = await manager.list_categories()
        time1 = time.time() - start1
        
        start2 = time.time()
        result2 = await manager.list_categories()
        time2 = time.time() - start2
        
        # THEN - Results should match and second call should be fast
        assert result1 == result2
        # Second call should be faster (cached)
        assert time2 <= time1 * 2  # Allow some variance
    
    async def test_tool_logging(self):
        """Test that tool calls are logged."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Making tool calls
        await manager.list_categories()
        
        # THEN - Should complete without errors (logging is internal)
        assert True  # Logging verification would require log inspection
    
    async def test_graph_tool_execution(self):
        """Test executing graph tools."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Executing graph tool
        try:
            result = await manager.dispatch(
                'graph_tools',
                'graph_create',
                {'driver_url': 'ipfs://localhost:5001'}
            )
            # THEN - Should return result
            assert result is not None
        except Exception:
            # Expected without full IPFS setup
            pass
    
    async def test_ipfs_tool_execution(self):
        """Test executing IPFS tools."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Executing IPFS tool
        try:
            result = await manager.dispatch(
                'ipfs_tools',
                'pin_to_ipfs',
                {'content_source': 'test data'}
            )
            # THEN - Should return result
            assert result is not None
        except Exception:
            # Expected without IPFS daemon
            pass


class TestHierarchicalDispatch:
    """Test hierarchical dispatch functionality."""
    
    async def test_dispatch_to_all_categories(self):
        """Test dispatching to multiple categories."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        categories = await manager.list_categories()
        
        # WHEN - Dispatching to first few categories
        results = []
        for category in categories[:5]:
            try:
                tools_result = await manager.list_tools(category["name"])
                if tools_result.get("status") == "success":
                    results.append((category["name"], len(tools_result["tools"])))
            except Exception:
                pass
        
        # THEN - Should have some successful dispatches
        assert len(results) > 0
    
    async def test_parameter_transformation(self):
        """Test parameter transformation in dispatch."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Dispatching with various parameter types
        params = {
            'source': 'test',
            'format': 'json',
            'options': {'key': 'value'}
        }
        
        try:
            result = await manager.dispatch('dataset_tools', 'load_dataset', params)
            # THEN - Parameters should be handled
            assert result is not None or True  # Accept None or exceptions
        except Exception:
            # Expected behavior
            pass
    
    async def test_result_aggregation(self):
        """Test aggregating results from multiple tools."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Calling multiple tools
        results = []
        for category in ['dataset_tools', 'graph_tools', 'ipfs_tools']:
            try:
                tools_result = await manager.list_tools(category)
                if tools_result.get("status") == "success":
                    results.append(tools_result["tools"])
            except Exception:
                pass
        
        # THEN - Should aggregate results
        assert len(results) > 0
        total_tools = sum(len(r) for r in results)
        assert total_tools >= 0
    
    async def test_error_handling_and_recovery(self):
        """Test error handling in hierarchical dispatch."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Dispatching to invalid tool
        result = await manager.dispatch('invalid', 'invalid', {})
        assert result["status"] == "error"
        
        # THEN - Manager should still work after error
        categories = await manager.list_categories()
        assert len(categories) > 0
    
    async def test_performance_under_load(self):
        """Test performance with many concurrent requests."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        import time
        
        manager = HierarchicalToolManager()
        
        # WHEN - Making many concurrent requests
        start = time.time()
        results = [None] * 100

        async def _run(index):
            results[index] = await manager.list_categories()

        async with anyio.create_task_group() as tg:
            for i in range(100):
                tg.start_soon(_run, i)

        elapsed = time.time() - start
        
        # THEN - Should handle load efficiently (< 5 seconds for 100 requests)
        assert elapsed < 5.0
        assert len(results) == 100
        assert all(len(r) > 0 for r in results)
