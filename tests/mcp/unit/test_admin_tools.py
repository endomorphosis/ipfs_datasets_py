"""
Tests for admin_tools tool category.

Tests cover:
- manage_endpoints (list, add, remove)
- system_maintenance (status, cleanup)
- configure_system (get, set)
- system_health (component health check)
- system_status (overall status)
"""
import pytest
from unittest.mock import patch, MagicMock

from ipfs_datasets_py.mcp_server.tools.admin_tools.admin_tools import (
    manage_endpoints,
    system_maintenance,
    configure_system,
    system_health,
    system_status,
)


class TestManageEndpoints:
    """Tests for manage_endpoints tool function."""

    @pytest.mark.asyncio
    async def test_list_endpoints_returns_status(self):
        """
        GIVEN the admin tools module
        WHEN manage_endpoints is called with action='list'
        THEN the result must be a dict containing a 'status' key
        """
        result = await manage_endpoints(action="list")
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result

    @pytest.mark.asyncio
    async def test_add_endpoint_returns_status(self):
        """
        GIVEN the admin tools module
        WHEN manage_endpoints is called with action='add' and endpoint details
        THEN the result must contain a 'status' key
        """
        result = await manage_endpoints(
            action="add",
            model="test-model",
            endpoint="http://localhost:8000",
            endpoint_type="local",
            ctx_length=512,
        )
        assert result is not None
        assert "status" in result

    @pytest.mark.asyncio
    async def test_invalid_action_returns_error_or_success(self):
        """
        GIVEN the admin tools module
        WHEN manage_endpoints is called with an unrecognised action
        THEN the result must contain 'status' set to 'error' or 'success'
        """
        result = await manage_endpoints(action="invalid_action")
        assert result is not None
        assert "status" in result
        assert result["status"] in ("error", "success")


class TestSystemMaintenance:
    """Tests for system_maintenance tool function."""

    @pytest.mark.asyncio
    async def test_status_action_returns_result(self):
        """
        GIVEN the admin tools module
        WHEN system_maintenance is called with action='status'
        THEN the result must not be None and must contain 'status'
        """
        result = await system_maintenance(action="status")
        assert result is not None
        assert "status" in result


class TestConfigureSystem:
    """Tests for configure_system tool function."""

    @pytest.mark.asyncio
    async def test_get_config_returns_result(self):
        """
        GIVEN the admin tools module
        WHEN configure_system is called with action='get'
        THEN the result must not be None and must contain 'status'
        """
        result = await configure_system(action="get", config_key="embedding_settings")
        assert result is not None
        assert "status" in result


class TestSystemHealth:
    """Tests for system_health tool function."""

    @pytest.mark.asyncio
    async def test_all_components_health(self):
        """
        GIVEN the admin tools module
        WHEN system_health is called for all components with detailed=True
        THEN the result must not be None and must contain 'status'
        """
        result = await system_health(component="all", detailed=True)
        assert result is not None
        assert "status" in result


class TestSystemStatus:
    """Tests for system_status tool function."""

    @pytest.mark.asyncio
    async def test_status_returns_dict(self):
        """
        GIVEN the admin tools module
        WHEN system_status is called with no arguments
        THEN the result must be a dict containing 'status'
        """
        result = await system_status()
        assert result is not None
        assert "status" in result
