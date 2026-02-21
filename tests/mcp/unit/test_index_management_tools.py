"""
Phase B2 (session 30): Unit tests for index_management_tools tool category.

Tests cover:
- load_index: vector index loading and management
- manage_shards: shard operations on distributed index
- monitor_index_status: index health monitoring
- manage_index_configuration: index configuration management
"""
from __future__ import annotations

import pytest


class TestLoadIndex:
    """Tests for load_index tool function."""

    @pytest.mark.asyncio
    async def test_load_action_returns_dict(self):
        """
        GIVEN action='load' with a dataset name
        WHEN load_index is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            load_index,
        )
        result = await load_index(action="load", dataset="test_dataset")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_status_action_returns_dict(self):
        """
        GIVEN action='status'
        WHEN load_index is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            load_index,
        )
        result = await load_index(action="status")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_create_action_returns_dict(self):
        """
        GIVEN action='create'
        WHEN load_index is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            load_index,
        )
        result = await load_index(action="create", dataset="new_dataset")
        assert isinstance(result, dict)


class TestManageShards:
    """Tests for manage_shards tool function."""

    @pytest.mark.asyncio
    async def test_create_action_returns_dict(self):
        """
        GIVEN action='create'
        WHEN manage_shards is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            manage_shards,
        )
        result = await manage_shards(action="create", dataset="test_dataset", num_shards=4)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_list_action_returns_dict(self):
        """
        GIVEN action='list'
        WHEN manage_shards is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            manage_shards,
        )
        result = await manage_shards(action="list")
        assert isinstance(result, dict)


class TestMonitorIndexStatus:
    """Tests for monitor_index_status tool function."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """
        GIVEN basic monitor call with no filter
        WHEN monitor_index_status is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            monitor_index_status,
        )
        result = await monitor_index_status()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_with_dataset_name(self):
        """
        GIVEN a specific index_id
        WHEN monitor_index_status is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            monitor_index_status,
        )
        result = await monitor_index_status(index_id="my_index")
        assert isinstance(result, dict)


class TestManageIndexConfiguration:
    """Tests for manage_index_configuration tool function."""

    @pytest.mark.asyncio
    async def test_get_action_returns_dict(self):
        """
        GIVEN action='get'
        WHEN manage_index_configuration is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            manage_index_configuration,
        )
        result = await manage_index_configuration(action="get")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_validate_action_returns_dict(self):
        """
        GIVEN action='get_config' with a specific index_id
        WHEN manage_index_configuration is called
        THEN result must be a dict.
        """
        from ipfs_datasets_py.mcp_server.tools.index_management_tools.index_management_tools import (
            manage_index_configuration,
        )
        result = await manage_index_configuration(
            action="get_config",
            index_id="test_index",
        )
        assert isinstance(result, dict)
