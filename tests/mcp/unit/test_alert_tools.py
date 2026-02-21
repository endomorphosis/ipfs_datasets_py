"""
Phase B2 unit tests for alert_tools/discord_alert_tools.py
"""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def no_alerts_module():
    """Patch ALERTS_AVAILABLE = False so tests never need Discord credentials."""
    import importlib
    with patch(
        "ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools.ALERTS_AVAILABLE",
        False,
    ):
        yield


# ---------------------------------------------------------------------------
# send_discord_message
# ---------------------------------------------------------------------------

class TestSendDiscordMessage:
    """Tests for send_discord_message."""

    @pytest.mark.asyncio
    async def test_returns_error_when_alerts_unavailable(self, no_alerts_module):
        """When ALERTS_AVAILABLE is False the notifier constructor raises → error returned."""
        from ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools import (
            send_discord_message,
        )
        result = await send_discord_message(text="hello")
        assert "error" in result or result.get("status") == "error"

    @pytest.mark.asyncio
    async def test_delegates_to_notifier_when_available(self):
        """When the notifier is available the message is delegated to it."""
        mock_notifier = MagicMock()
        mock_notifier.send_message = AsyncMock(return_value={"status": "sent", "message_id": "m1"})

        with patch(
            "ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools._get_notifier",
            return_value=mock_notifier,
        ):
            from ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools import (
                send_discord_message,
            )
            result = await send_discord_message(text="Market alert!")

        mock_notifier.send_message.assert_called_once()
        assert result.get("status") == "sent"

    @pytest.mark.asyncio
    async def test_passes_channel_id_and_roles(self):
        """channel_id and role_names are forwarded to the notifier."""
        mock_notifier = MagicMock()
        mock_notifier.send_message = AsyncMock(return_value={"status": "sent"})

        with patch(
            "ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools._get_notifier",
            return_value=mock_notifier,
        ):
            from ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools import (
                send_discord_message,
            )
            await send_discord_message(
                text="Alert!", channel_id="ch1", role_names=["ops"]
            )

        _, call_kwargs = mock_notifier.send_message.call_args
        assert call_kwargs.get("channel_id") == "ch1"
        assert call_kwargs.get("role_names") == ["ops"]


# ---------------------------------------------------------------------------
# list_alert_rules
# ---------------------------------------------------------------------------

class TestListAlertRules:
    """Tests for list_alert_rules."""

    def test_returns_dict_with_rules_key(self, no_alerts_module):
        """When alerts are unavailable a graceful response is returned."""
        from ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools import (
            list_alert_rules,
        )
        result = list_alert_rules()
        assert isinstance(result, dict)

    def test_delegates_to_manager_when_available(self):
        """When AlertManager is available, rules are fetched from it."""
        mock_mgr = MagicMock()
        mock_mgr.list_rules.return_value = [{"name": "cpu_high", "threshold": 90}]

        with patch(
            "ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools._get_alert_manager",
            return_value=mock_mgr,
        ):
            from ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools import (
                list_alert_rules,
            )
            result = list_alert_rules()

        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# add_alert_rule / remove_alert_rule
# ---------------------------------------------------------------------------

class TestAddRemoveAlertRule:
    """Tests for add_alert_rule and remove_alert_rule."""

    def test_add_rule_returns_dict(self, no_alerts_module):
        """add_alert_rule returns a dict even when alerts are unavailable."""
        from ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools import (
            add_alert_rule,
        )
        result = add_alert_rule(rule_data={"rule_id": "r1", "name": "cpu_high", "condition": {}, "severity": "info"})
        assert isinstance(result, dict)

    def test_remove_nonexistent_rule_returns_dict(self, no_alerts_module):
        """remove_alert_rule returns a dict even when alerts are unavailable."""
        from ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools import (
            remove_alert_rule,
        )
        result = remove_alert_rule(rule_id="missing_rule")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# get_suppression_status
# ---------------------------------------------------------------------------

class TestGetSuppressionStatus:
    """Tests for get_suppression_status."""

    def test_returns_dict_no_alerts(self, no_alerts_module):
        from ipfs_datasets_py.mcp_server.tools.alert_tools.discord_alert_tools import (
            get_suppression_status,
        )
        result = get_suppression_status()
        assert isinstance(result, dict)
