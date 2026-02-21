"""
Phase B2 (session 30): Unit tests for rate_limiting_tools tool category.

Tests cover:
- configure_rate_limits: configure rate limit rules
- check_rate_limit: check if request is within limits
- manage_rate_limits: manage rate limit configuration
"""
from __future__ import annotations

import pytest


class TestConfigureRateLimits:
    """Tests for configure_rate_limits tool function."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """
        GIVEN a single rate limit config
        WHEN configure_rate_limits is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            configure_rate_limits,
        )
        result = await configure_rate_limits(
            limits=[
                {
                    "name": "test_api",
                    "strategy": "token_bucket",
                    "requests_per_second": 10.0,
                }
            ]
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_has_configured_count(self):
        """
        GIVEN one valid limit config
        WHEN configure_rate_limits is called
        THEN result must have 'configured_count' == 1.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            configure_rate_limits,
        )
        result = await configure_rate_limits(
            limits=[{"name": "my_api", "requests_per_second": 5.0}]
        )
        assert result["configured_count"] == 1

    @pytest.mark.asyncio
    async def test_empty_limits_list(self):
        """
        GIVEN an empty list of limits
        WHEN configure_rate_limits is called
        THEN configured_count must be 0 and errors must be empty.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            configure_rate_limits,
        )
        result = await configure_rate_limits(limits=[])
        assert result["configured_count"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_backup_included_when_requested(self):
        """
        GIVEN backup_current=True
        WHEN configure_rate_limits is called
        THEN result must include 'backup' key.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            configure_rate_limits,
        )
        result = await configure_rate_limits(limits=[], backup_current=True)
        assert "backup" in result


class TestCheckRateLimit:
    """Tests for check_rate_limit tool function."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """
        GIVEN a known limit name
        WHEN check_rate_limit is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            check_rate_limit,
        )
        result = await check_rate_limit("default", identifier="user_1")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_has_allowed_key(self):
        """
        GIVEN any identifier
        WHEN check_rate_limit is called
        THEN result must have 'allowed' bool key.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            check_rate_limit,
        )
        result = await check_rate_limit("default", identifier="user_2")
        assert "allowed" in result
        assert isinstance(result["allowed"], bool)

    @pytest.mark.asyncio
    async def test_includes_limit_name(self):
        """
        GIVEN limit_name='default'
        WHEN check_rate_limit is called
        THEN result must echo the limit_name back.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            check_rate_limit,
        )
        result = await check_rate_limit("default", identifier="user_3")
        assert result["limit_name"] == "default"


class TestManageRateLimits:
    """Tests for manage_rate_limits tool function."""

    @pytest.mark.asyncio
    async def test_list_action_returns_dict(self):
        """
        GIVEN action='list'
        WHEN manage_rate_limits is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            manage_rate_limits,
        )
        result = await manage_rate_limits(action="list")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_stats_action_returns_dict(self):
        """
        GIVEN action='stats'
        WHEN manage_rate_limits is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            manage_rate_limits,
        )
        result = await manage_rate_limits(action="stats")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_reset_action_returns_dict(self):
        """
        GIVEN action='reset'
        WHEN manage_rate_limits is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.rate_limiting_tools.rate_limiting_tools import (
            manage_rate_limits,
        )
        result = await manage_rate_limits(action="reset")
        assert isinstance(result, dict)
