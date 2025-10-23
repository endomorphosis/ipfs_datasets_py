#!/usr/bin/env python3
"""
Test suite for admin tools functionality.
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestAdminTools:
    """Test admin tools functionality."""

    @pytest.mark.asyncio
    async def test_manage_endpoints_list(self):
        """Test listing endpoints."""
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import manage_endpoints
        
        result = await manage_endpoints(action="list")
        
        assert result is not None
        assert "success" in result
        assert "endpoints" in result
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_manage_endpoints_add(self):
        """Test adding endpoints."""
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import manage_endpoints
        
        result = await manage_endpoints(
            action="add",
            model="test-model",
            endpoint="http://localhost:8000",
            endpoint_type="local",
            ctx_length=512
        )
        
        assert result is not None
        assert "success" in result
        assert result["success"] is True
    
    @pytest.mark.asyncio
    async def test_manage_system_config(self):
        """Test system configuration management."""
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import manage_system_config
        
        result = await manage_system_config(
            action="get",
            config_key="embedding_settings"
        )
        
        assert result is not None
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_system_health_check(self):
        """Test system health monitoring."""
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import system_health_check
        
        result = await system_health_check(
            component="all",
            detailed=True
        )
        
        assert result is not None
        assert "success" in result
        assert "health" in result or "components" in result
    
    @pytest.mark.asyncio
    async def test_manage_user_permissions(self):
        """Test user permission management."""
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import manage_user_permissions
        
        result = await manage_user_permissions(
            action="list",
            user_id="test-user"
        )
        
        assert result is not None
        assert "success" in result
    
    @pytest.mark.asyncio
    async def test_database_operations(self):
        """Test database management operations."""
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import database_operations
        
        result = await database_operations(
            operation="status",
            database="main"
        )
        
        assert result is not None
        assert "success" in result


class TestEnhancedAdminTools:
    """Test enhanced admin tools functionality."""

    @pytest.mark.asyncio
    async def test_enhanced_admin_import(self):
        """Test that enhanced admin tools can be imported."""
        try:
            from ipfs_datasets_py.mcp_server.tools.admin_tools.enhanced_admin_tools import (
                manage_service_registry,
                orchestrate_workflows,
                advanced_monitoring
            )
            assert True
        except ImportError as e:
            raise ImportError(f"Enhanced admin tools not available: {e}")
    
    @pytest.mark.asyncio
    async def test_service_registry_management(self):
        """Test service registry operations."""
        try:
            from ipfs_datasets_py.mcp_server.tools.admin_tools.enhanced_admin_tools import manage_service_registry
            
            result = await manage_service_registry(
                action="list",
                service_type="embedding"
            )
            
            assert result is not None
            assert "success" in result
        except ImportError:
            raise ImportError("Enhanced admin tools not available")
    
    @pytest.mark.asyncio
    async def test_workflow_orchestration(self):
        """Test workflow orchestration."""
        try:
            from ipfs_datasets_py.mcp_server.tools.admin_tools.enhanced_admin_tools import orchestrate_workflows
            
            result = await orchestrate_workflows(
                workflow_id="test-workflow",
                action="status"
            )
            
            assert result is not None
            assert "success" in result
        except ImportError:
            raise ImportError("Enhanced admin tools not available")


class TestAdminToolsIntegration:
    """Test admin tools integration with other components."""

    @pytest.mark.asyncio
    async def test_admin_tools_mcp_registration(self):
        """Test that admin tools are properly registered with MCP."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import get_registered_tools
        
        tools = get_registered_tools()
        admin_tools = [tool for tool in tools if 'admin' in tool.get('name', '').lower()]
        
        assert len(admin_tools) > 0, "Admin tools should be registered"
    
    @pytest.mark.asyncio
    async def test_admin_tools_error_handling(self):
        """Test error handling in admin tools."""
        from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import manage_endpoints
        
        # Test with invalid action
        result = await manage_endpoints(action="invalid_action")
        
        assert result is not None
        assert "success" in result
        # Should handle error gracefully
        assert result["status"] in ["error", "success"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
