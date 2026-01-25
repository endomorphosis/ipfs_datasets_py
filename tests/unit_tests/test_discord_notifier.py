"""
Unit tests for Discord Notifier

Tests the DiscordNotifier, BotClient, and WebhookClient classes.
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from ipfs_datasets_py.alerts.discord_notifier import (
    DiscordNotifier,
    DiscordEmbed,
    BotClient,
    WebhookClient,
    AIOHTTP_AVAILABLE,
    DiscordBackend
)

class TestDiscordEmbed:
    """Test DiscordEmbed data class."""
    
    def test_embed_initialization_defaults(self):
        """
        GIVEN no parameters
        WHEN DiscordEmbed is initialized
        THEN expect default values to be set
        """
        embed = DiscordEmbed()
        
        assert embed.title is None
        assert embed.description is None
        assert embed.color == 0x3498db  # Default blue
        assert embed.fields == []
        assert embed.footer is None
        assert embed.timestamp is None
    
    def test_embed_initialization_with_params(self):
        """
        GIVEN title, description, and color parameters
        WHEN DiscordEmbed is initialized
        THEN expect parameters to be set correctly
        """
        embed = DiscordEmbed(
            title="Test Title",
            description="Test Description",
            color=0xff0000
        )
        
        assert embed.title == "Test Title"
        assert embed.description == "Test Description"
        assert embed.color == 0xff0000
    
    def test_embed_to_dict(self):
        """
        GIVEN a DiscordEmbed with various fields
        WHEN to_dict() is called
        THEN expect correct dictionary representation
        """
        fields = [
            {"name": "Field 1", "value": "Value 1", "inline": True}
        ]
        
        embed = DiscordEmbed(
            title="Test",
            description="Description",
            color=0x00ff00,
            fields=fields,
            footer="Footer text"
        )
        
        result = embed.to_dict()
        
        assert result['title'] == "Test"
        assert result['description'] == "Description"
        assert result['color'] == 0x00ff00
        assert result['fields'] == fields
        assert result['footer'] == {'text': "Footer text"}
    
    def test_embed_to_dict_minimal(self):
        """
        GIVEN a minimal DiscordEmbed with only required fields
        WHEN to_dict() is called
        THEN expect dictionary with only set fields
        """
        embed = DiscordEmbed(title="Test")
        
        result = embed.to_dict()
        
        assert result['title'] == "Test"
        assert 'description' not in result or result['description'] is None
        assert 'color' in result


@pytest.mark.asyncio
class TestWebhookClient:
    """Test WebhookClient for webhook-based Discord notifications."""
    
    def test_webhook_client_initialization(self):
        """
        GIVEN a webhook URL
        WHEN WebhookClient is initialized
        THEN expect webhook_url to be set and session to be None
        """
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        if not AIOHTTP_AVAILABLE:
            with pytest.raises(ImportError, match="aiohttp is required"):
                WebhookClient(webhook_url=webhook_url)
            return
        client = WebhookClient(webhook_url=webhook_url)
        
        assert client.webhook_url == webhook_url
        assert client.session is None
    
    def test_webhook_client_role_map(self):
        """
        GIVEN a webhook URL and role_map
        WHEN WebhookClient is initialized
        THEN expect role_map to be set correctly
        """
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        role_map = {"trader": "123456789"}
        if not AIOHTTP_AVAILABLE:
            with pytest.raises(ImportError, match="aiohttp is required"):
                WebhookClient(webhook_url=webhook_url, role_map=role_map)
            return
        
        client = WebhookClient(webhook_url=webhook_url, role_map=role_map)
        
        assert client.role_map == role_map
    
    @patch('ipfs_datasets_py.alerts.discord_notifier.AIOHTTP_AVAILABLE', False)
    def test_webhook_client_without_aiohttp(self):
        """
        GIVEN aiohttp is not available
        WHEN WebhookClient is initialized
        THEN expect ImportError to be raised
        """
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        
        with pytest.raises(ImportError, match="aiohttp is required"):
            WebhookClient(webhook_url=webhook_url)
    
    @patch('ipfs_datasets_py.alerts.discord_notifier.aiohttp.ClientSession')
    async def test_send_message_plain_text(self, mock_session_cls):
        """
        GIVEN a WebhookClient and plain text message
        WHEN send_message is called
        THEN expect correct HTTP POST to webhook URL
        """
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        if not AIOHTTP_AVAILABLE:
            pytest.skip("aiohttp not available")
        client = WebhookClient(webhook_url=webhook_url)
        
        # Create proper async context manager mock
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value='{"id": "123"}')
        
        # Mock the context manager
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        
        # Mock aiohttp session
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)
        mock_session.closed = False
        mock_session_cls.return_value = mock_session
        
        result = await client.send_message(text="Test message")
        
        assert result['status'] == 'success'
    
    @patch('ipfs_datasets_py.alerts.discord_notifier.aiohttp.ClientSession')
    async def test_send_message_with_embed(self, mock_session_cls):
        """
        GIVEN a WebhookClient, text, and embed
        WHEN send_message is called
        THEN expect correct payload with embed
        """
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        if not AIOHTTP_AVAILABLE:
            pytest.skip("aiohttp not available")
        client = WebhookClient(webhook_url=webhook_url)
        
        embed = DiscordEmbed(title="Test Embed", description="Test Description")
        
        # Create proper async context manager mock
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value='{"id": "123"}')
        
        # Mock the context manager
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        
        # Mock aiohttp session
        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_ctx)
        mock_session.closed = False
        mock_session_cls.return_value = mock_session
        
        result = await client.send_message(text="Test", embed=embed)
        
        assert result['status'] == 'success'
    
    async def test_close_session(self):
        """
        GIVEN a WebhookClient with an open session
        WHEN close() is called
        THEN expect session to be closed
        """
        webhook_url = "https://discord.com/api/webhooks/123/abc"
        if not AIOHTTP_AVAILABLE:
            pytest.skip("aiohttp not available")
        client = WebhookClient(webhook_url=webhook_url)
        
        mock_session = AsyncMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        
        client.session = mock_session
        
        await client.close()
        
        mock_session.close.assert_called_once()


class TestDiscordNotifier:
    """Test DiscordNotifier unified interface."""
    
    def test_notifier_initialization_webhook_mode(self):
        """
        GIVEN webhook mode and webhook URL
        WHEN DiscordNotifier is initialized
        THEN expect WebhookClient backend to be created
        """
        if not AIOHTTP_AVAILABLE:
            with pytest.raises(ImportError, match="aiohttp is required"):
                DiscordNotifier(
                    mode="webhook",
                    webhook_url="https://discord.com/api/webhooks/123/abc"
                )
            return
        notifier = DiscordNotifier(
            mode="webhook",
            webhook_url="https://discord.com/api/webhooks/123/abc"
        )
        
        assert notifier.mode == "webhook"
        assert isinstance(notifier.backend, WebhookClient)
    
    @patch('ipfs_datasets_py.alerts.discord_notifier.DISCORD_PY_AVAILABLE', False)
    def test_notifier_bot_mode_without_discord_py(self):
        """
        GIVEN bot mode but discord.py not available
        WHEN DiscordNotifier is initialized
        THEN expect ImportError to be raised
        """
        with pytest.raises(ImportError, match="discord.py is required"):
            DiscordNotifier(
                mode="bot",
                bot_token="test_token",
                guild_id="123",
                channel_id="456"
            )
    
    def test_notifier_invalid_mode(self):
        """
        GIVEN an invalid mode
        WHEN DiscordNotifier is initialized
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="Invalid mode"):
            DiscordNotifier(mode="invalid")
    
    @patch.dict('os.environ', {
        'DISCORD_MODE': 'webhook',
        'DISCORD_WEBHOOK_URL': 'https://discord.com/api/webhooks/123/abc'
    })
    def test_notifier_load_from_env(self):
        """
        GIVEN Discord configuration in environment variables
        WHEN DiscordNotifier is initialized without parameters
        THEN expect configuration to be loaded from environment
        """
        if not AIOHTTP_AVAILABLE:
            with pytest.raises(ImportError, match="aiohttp is required"):
                DiscordNotifier()
            return
        notifier = DiscordNotifier()
        
        assert notifier.mode == "webhook"
        assert isinstance(notifier.backend, WebhookClient)
    
    @patch.dict('os.environ', {
        'DISCORD_ROLE_MAP': '{"trader":"123456","analyst":"789012"}'
    })
    def test_notifier_load_role_map_from_env(self):
        """
        GIVEN role map in environment variable as JSON
        WHEN DiscordNotifier is initialized
        THEN expect role_map to be parsed and loaded
        """
        if not AIOHTTP_AVAILABLE:
            with pytest.raises(ImportError, match="aiohttp is required"):
                DiscordNotifier(
                    mode="webhook",
                    webhook_url="https://discord.com/api/webhooks/123/abc"
                )
            return
        notifier = DiscordNotifier(
            mode="webhook",
            webhook_url="https://discord.com/api/webhooks/123/abc"
        )
        
        # Role map should be passed to backend
        assert notifier.backend.role_map is not None


@pytest.mark.asyncio
class TestDiscordNotifierAsyncMethods:
    """Test async methods of DiscordNotifier."""
    
    async def test_send_message_delegates_to_backend(self):
        """
        GIVEN a DiscordNotifier with mocked backend
        WHEN send_message is called
        THEN expect backend.send_message to be called with correct parameters
        """
        if not AIOHTTP_AVAILABLE:
            pytest.skip("aiohttp not available")
        notifier = DiscordNotifier(
            mode="webhook",
            webhook_url="https://discord.com/api/webhooks/123/abc"
        )
        
        # Mock backend
        notifier.backend.send_message = AsyncMock(return_value={'status': 'success'})
        
        result = await notifier.send_message(text="Test message")
        
        assert result['status'] == 'success'
        notifier.backend.send_message.assert_called_once()
    
    async def test_context_manager(self):
        """
        GIVEN a DiscordNotifier
        WHEN used as async context manager
        THEN expect proper initialization and cleanup
        """
        if not AIOHTTP_AVAILABLE:
            pytest.skip("aiohttp not available")
        notifier = DiscordNotifier(
            mode="webhook",
            webhook_url="https://discord.com/api/webhooks/123/abc"
        )
        
        # Mock backend close
        notifier.backend.close = AsyncMock()
        
        async with notifier as n:
            assert n is notifier
        
        notifier.backend.close.assert_called_once()
    
    async def test_send_message_without_backend(self):
        """
        GIVEN a DiscordNotifier with backend set to None
        WHEN send_message is called
        THEN expect error response
        """
        if not AIOHTTP_AVAILABLE:
            pytest.skip("aiohttp not available")
        notifier = DiscordNotifier(
            mode="webhook",
            webhook_url="https://discord.com/api/webhooks/123/abc"
        )
        notifier.backend = None
        
        result = await notifier.send_message(text="Test")
        
        assert result['status'] == 'error'
        assert 'Backend not initialized' in result['error']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
