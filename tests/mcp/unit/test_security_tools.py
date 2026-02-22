"""
Tests for security_tools tool category.

Tests cover:
- check_access_permission: verify user permission for a resource
"""
import pytest

from ipfs_datasets_py.mcp_server.tools.security_tools.check_access_permission import (
    check_access_permission,
)


class TestCheckAccessPermission:
    """Tests for check_access_permission tool function."""

    @pytest.mark.asyncio
    async def test_read_permission_returns_dict(self):
        """
        GIVEN the security_tools module
        WHEN check_access_permission is called with a resource_id
        THEN the result must be a dict containing 'status' or 'allowed'
        """
        result = await check_access_permission(
            resource_id="dataset_001",
            user_id="user_alice",
            permission_type="read",
        )
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result or "allowed" in result or "permitted" in result

    @pytest.mark.asyncio
    async def test_write_permission_returns_dict(self):
        """
        GIVEN the security_tools module
        WHEN check_access_permission is called for a write permission
        THEN the result must be a dict
        """
        result = await check_access_permission(
            resource_id="dataset_001",
            user_id="user_bob",
            permission_type="write",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_delete_permission_returns_dict(self):
        """
        GIVEN the security_tools module
        WHEN check_access_permission is called for a delete permission
        THEN the result must be a dict
        """
        result = await check_access_permission(
            resource_id="dataset_001",
            permission_type="delete",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_with_resource_type_returns_dict(self):
        """
        GIVEN the security_tools module
        WHEN check_access_permission is called with a resource_type
        THEN the result must be a dict
        """
        result = await check_access_permission(
            resource_id="report_007",
            user_id="user_charlie",
            permission_type="read",
            resource_type="report",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_share_permission_returns_dict(self):
        """
        GIVEN the security_tools module
        WHEN check_access_permission is called for share permission
        THEN the result must be a dict
        """
        result = await check_access_permission(
            resource_id="model_weights_v2",
            user_id="user_dave",
            permission_type="share",
        )
        assert result is not None
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_no_user_id_returns_dict(self):
        """
        GIVEN the security_tools module
        WHEN check_access_permission is called without a user_id
        THEN the result must still be a dict (anonymous access check)
        """
        result = await check_access_permission(resource_id="public_dataset")
        assert result is not None
        assert isinstance(result, dict)
