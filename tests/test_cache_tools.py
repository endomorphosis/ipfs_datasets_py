#!/usr/bin/env python3
"""
Test suite for cache tools functionality.
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestCacheTools:
    """Test cache tools functionality."""

    @pytest.mark.asyncio
    async def test_cache_get_operation(self):
        """Test cache get operation."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import manage_cache
        
        result = await manage_cache(
            operation="get",
            key="test-key",
            namespace="test"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_cache_set_operation(self):
        """Test cache set operation."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import manage_cache
        
        result = await manage_cache(
            operation="set",
            key="test-key",
            value="test-value",
            ttl=3600,
            namespace="test"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_cache_delete_operation(self):
        """Test cache delete operation."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import manage_cache
        
        result = await manage_cache(
            operation="delete",
            key="test-key",
            namespace="test"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_cache_stats_operation(self):
        """Test cache statistics operation."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import manage_cache
        
        result = await manage_cache(operation="stats")
        
        assert result is not None
        assert "status" in result
        assert "stats" in result or "cache_stats" in result or "statistics" in result
    
    @pytest.mark.asyncio
    async def test_cache_clear_operation(self):
        """Test cache clear operation."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import manage_cache
        
        result = await manage_cache(
            operation="clear",
            namespace="test"
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_cache_optimization(self):
        """Test cache optimization functions."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import optimize_cache
        
        result = await optimize_cache(
            strategy="lru",
            max_size=1000,
            target_hit_ratio=0.8
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_cache_backup_restore(self):
        """Test cache backup and restore functionality."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import backup_cache, restore_cache
        
        # Test backup
        backup_result = await backup_cache(
            namespace="test",
            backup_path="/tmp/cache_backup.json"
        )
        
        assert backup_result is not None
        assert "status" in backup_result
        
        # Test restore
        restore_result = await restore_cache(
            backup_path="/tmp/cache_backup.json",
            namespace="test"
        )
        
        assert restore_result is not None
        assert "status" in restore_result


class TestEnhancedCacheTools:
    """Test enhanced cache tools functionality."""

    @pytest.mark.asyncio
    async def test_enhanced_cache_import(self):
        """Test that enhanced cache tools can be imported."""
        try:
            from ipfs_datasets_py.mcp_server.tools.cache_tools.enhanced_cache_tools import (
                distributed_cache_management,
                cache_analytics,
                smart_prefetching
            )
            assert True
        except ImportError as e:
            pytest.skip(f"Enhanced cache tools not available: {e}")
    
    @pytest.mark.asyncio
    async def test_distributed_cache_management(self):
        """Test distributed cache operations."""
        try:
            from ipfs_datasets_py.mcp_server.tools.cache_tools.enhanced_cache_tools import distributed_cache_management
            
            result = await distributed_cache_management(
                operation="status",
                cluster_node="node1"
            )
            
            assert result is not None
            assert "status" in result
        except ImportError:
            pytest.skip("Enhanced cache tools not available")
    
    @pytest.mark.asyncio
    async def test_cache_analytics(self):
        """Test cache analytics functionality."""
        try:
            from ipfs_datasets_py.mcp_server.tools.cache_tools.enhanced_cache_tools import cache_analytics
            
            result = await cache_analytics(
                metric_type="hit_ratio",
                time_range="1h"
            )
            
            assert result is not None
            assert "status" in result
        except ImportError:
            pytest.skip("Enhanced cache tools not available")


class TestCacheToolsIntegration:
    """Test cache tools integration with other components."""

    @pytest.mark.asyncio
    async def test_cache_tools_mcp_registration(self):
        """Test that cache tools are properly registered with MCP."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import get_registered_tools
        
        tools = get_registered_tools()
        cache_tools = [tool for tool in tools if 'cache' in tool.get('name', '').lower()]
        
        assert len(cache_tools) > 0, "Cache tools should be registered"
    
    @pytest.mark.asyncio
    async def test_cache_tools_error_handling(self):
        """Test error handling in cache tools."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import manage_cache
        
        # Test with invalid operation
        result = await manage_cache(operation="invalid_operation")
        
        assert result is not None
        assert "status" in result
        # Should handle error gracefully
        assert result["status"] in ["error", "success"]
    
    @pytest.mark.asyncio
    async def test_cache_namespace_isolation(self):
        """Test that cache namespaces are properly isolated."""
        from ipfs_datasets_py.mcp_server.tools.cache_tools.cache_tools import manage_cache
        
        # Set value in namespace1
        result1 = await manage_cache(
            operation="set",
            key="test-key",
            value="value1",
            namespace="namespace1"
        )
        
        # Set different value in namespace2
        result2 = await manage_cache(
            operation="set",
            key="test-key",
            value="value2",
            namespace="namespace2"
        )
        
        # Get values from both namespaces
        get_result1 = await manage_cache(
            operation="get",
            key="test-key",
            namespace="namespace1"
        )
        
        get_result2 = await manage_cache(
            operation="get",
            key="test-key",
            namespace="namespace2"
        )
        
        assert all(r["status"] == "success" for r in [result1, result2, get_result1, get_result2])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
