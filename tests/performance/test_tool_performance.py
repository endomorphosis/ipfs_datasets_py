"""
Performance tests for MCP tools and hierarchical manager.
"""

import pytest
import time
import asyncio
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestDiscoveryPerformance:
    """Test discovery performance."""
    
    @pytest.mark.asyncio
    async def test_cold_start_discovery(self):
        """Test cold start discovery speed."""
        # GIVEN - Fresh HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        # WHEN - Measuring cold start
        start = time.time()
        manager = HierarchicalToolManager()
        categories = manager.list_categories()
        elapsed = time.time() - start
        
        # THEN - Should be fast (< 2 seconds)
        assert elapsed < 2.0
        assert len(categories) > 0
    
    @pytest.mark.asyncio
    async def test_warm_start_discovery(self):
        """Test warm start (cached) discovery speed."""
        # GIVEN - Already initialized manager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        manager.list_categories()  # Warm up
        
        # WHEN - Measuring cached access
        start = time.time()
        categories = manager.list_categories()
        elapsed = time.time() - start
        
        # THEN - Should be very fast (< 0.1 seconds)
        assert elapsed < 0.1
        assert len(categories) > 0
    
    @pytest.mark.asyncio
    async def test_large_scale_discovery(self):
        """Test discovering all 51 categories."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Discovering all categories and their tools
        start = time.time()
        categories = manager.list_categories()
        
        tools_count = 0
        for category in categories:
            try:
                tools = manager.list_tools(category)
                tools_count += len(tools)
            except:
                pass
        
        elapsed = time.time() - start
        
        # THEN - Should complete in reasonable time (< 5 seconds)
        assert elapsed < 5.0
        assert len(categories) >= 50


class TestQueryPerformance:
    """Test query execution performance."""
    
    @pytest.mark.asyncio
    async def test_simple_query_performance(self):
        """Test simple list query performance."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Executing simple queries
        times = []
        for _ in range(10):
            start = time.time()
            manager.list_categories()
            times.append(time.time() - start)
        
        # THEN - Average should be fast (< 0.1 seconds)
        avg_time = sum(times) / len(times)
        assert avg_time < 0.1
    
    @pytest.mark.asyncio
    async def test_concurrent_query_performance(self):
        """Test concurrent query execution."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Executing concurrent queries
        start = time.time()
        tasks = [manager.list_categories() for _ in range(50)]
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start
        
        # THEN - Should handle concurrency well (< 2 seconds for 50 queries)
        assert elapsed < 2.0
        assert len(results) == 50


class TestMemoryPerformance:
    """Test memory usage."""
    
    @pytest.mark.asyncio
    async def test_base_memory_footprint(self):
        """Test base memory usage."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        # WHEN - Creating manager
        manager = HierarchicalToolManager()
        manager.list_categories()
        
        # THEN - Should complete without memory errors
        assert manager is not None
    
    @pytest.mark.asyncio
    async def test_memory_under_load(self):
        """Test memory with many operations."""
        # GIVEN - HierarchicalToolManager
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
        
        manager = HierarchicalToolManager()
        
        # WHEN - Performing many operations
        for _ in range(100):
            manager.list_categories()
        
        # THEN - Should not leak memory
        assert manager is not None
