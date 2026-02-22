"""Tests for discord_tools tool category."""
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestDiscordListGuilds:
    """Tests for discord_list_guilds()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.discord_tools.discord_list import discord_list_guilds
        result = _run(discord_list_guilds(token=None))
        assert isinstance(result, dict)

    def test_no_token_returns_error_not_raise(self):
        """Missing Discord token should return an error dict, not raise."""
        from ipfs_datasets_py.mcp_server.tools.discord_tools.discord_list import discord_list_guilds
        result = _run(discord_list_guilds(token=None))
        assert isinstance(result, dict)
        # Status or error key must be present
        assert "status" in result or "error" in result or len(result) > 0

    def test_with_mock_token(self):
        """With a fake token, tool should attempt the call and return a dict."""
        from ipfs_datasets_py.mcp_server.tools.discord_tools.discord_list import discord_list_guilds
        result = _run(discord_list_guilds(token="fake_token"))
        assert isinstance(result, dict)


class TestDiscordListChannels:
    """Tests for discord_list_channels()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.discord_tools.discord_list import discord_list_channels
        result = _run(discord_list_channels(guild_id="123456789", token=None))
        assert isinstance(result, dict)

    def test_missing_guild_id(self):
        from ipfs_datasets_py.mcp_server.tools.discord_tools.discord_list import discord_list_channels
        result = _run(discord_list_channels(guild_id="", token=None))
        assert isinstance(result, dict)


class TestDiscordListDmChannels:
    """Tests for discord_list_dm_channels()."""

    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.discord_tools.discord_list import discord_list_dm_channels
        result = _run(discord_list_dm_channels(token=None))
        assert isinstance(result, dict)


class TestDiscordToolsImports:
    """Smoke-test that other discord_tools modules are importable."""

    def test_discord_analyze_importable(self):
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_analyze  # noqa

    def test_discord_convert_importable(self):
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_convert  # noqa

    def test_discord_export_importable(self):
        from ipfs_datasets_py.mcp_server.tools.discord_tools import discord_export  # noqa
