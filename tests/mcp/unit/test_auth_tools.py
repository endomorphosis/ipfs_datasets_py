"""
Tests for auth_tools tool category.

Tests cover:
- authenticate_user (local auth)
- validate_token (permission check)
- get_user_info (token introspection)
"""
import pytest
from unittest.mock import patch, MagicMock

from ipfs_datasets_py.mcp_server.tools.auth_tools.auth_tools import (
    authenticate_user,
    validate_token,
    get_user_info,
)


class TestAuthenticateUser:
    """Tests for authenticate_user tool function."""

    @pytest.mark.asyncio
    async def test_valid_credentials_returns_status(self):
        """
        GIVEN the auth tools module
        WHEN authenticate_user is called with credentials
        THEN the result must be a dict containing a 'status' key
        """
        result = await authenticate_user(
            username="test_user",
            password="test_password",
            auth_method="local",
        )
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result

    @pytest.mark.asyncio
    async def test_empty_credentials_returns_status(self):
        """
        GIVEN the auth tools module
        WHEN authenticate_user is called with empty credentials
        THEN the result must still be a dict (error response)
        """
        result = await authenticate_user(username="", password="")
        assert result is not None
        assert "status" in result


class TestValidateToken:
    """Tests for validate_token tool function."""

    @pytest.mark.asyncio
    async def test_invalid_token_returns_status(self):
        """
        GIVEN the auth tools module
        WHEN validate_token is called with a dummy token
        THEN the result must be a dict containing 'status'
        """
        result = await validate_token(token="dummy_token_xyz")
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result

    @pytest.mark.asyncio
    async def test_token_with_permission_check_returns_status(self):
        """
        GIVEN the auth tools module
        WHEN validate_token is called with required_permission
        THEN the result must contain 'status'
        """
        result = await validate_token(
            token="dummy_token_xyz",
            required_permission="read",
        )
        assert result is not None
        assert "status" in result


class TestGetUserInfo:
    """Tests for get_user_info tool function."""

    @pytest.mark.asyncio
    async def test_get_user_info_returns_dict(self):
        """
        GIVEN the auth tools module
        WHEN get_user_info is called with a token
        THEN the result must be a dict containing 'status'
        """
        result = await get_user_info(token="dummy_token_xyz")
        assert result is not None
        assert isinstance(result, dict)
        assert "status" in result
