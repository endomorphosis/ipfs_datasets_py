"""
Discord Notifier for IPFS Datasets Alert System

This module provides a unified Discord notification system with two backends:
1. Bot Client (discord.py) - For full bot integration with role mentions
2. Webhook Client (aiohttp) - For simple webhook-based notifications

The notifier supports:
- Plain text messages
- Rich embeds (title, description, fields, color)
- File attachments
- Thread/channel targeting
- Role mentions (bot mode only)
"""

from __future__ import annotations

import anyio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import json

logger = logging.getLogger(__name__)

# Optional imports for Discord backends
try:
    import discord
    DISCORD_PY_AVAILABLE = True
except ImportError:
    DISCORD_PY_AVAILABLE = False
    logger.warning("discord.py not available. Bot client will not work.")

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    logger.warning("aiohttp not available. Webhook client will not work.")


@dataclass
class DiscordEmbed:
    """
    Represents a Discord embed message.
    
    Attributes:
        title: Embed title
        description: Main embed content
        color: Embed color (hex int, e.g., 0x00ff00 for green)
        fields: List of field dictionaries with 'name' and 'value' keys
        footer: Footer text
        timestamp: ISO timestamp string
        url: URL for the embed title
        thumbnail_url: URL for thumbnail image
        image_url: URL for main image
    """
    title: Optional[str] = None
    description: Optional[str] = None
    color: int = 0x3498db  # Default blue
    fields: List[Dict[str, Any]] = field(default_factory=list)
    footer: Optional[str] = None
    timestamp: Optional[str] = None
    url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for Discord API."""
        embed_dict = {}
        
        if self.title:
            embed_dict['title'] = self.title
        if self.description:
            embed_dict['description'] = self.description
        if self.color:
            embed_dict['color'] = self.color
        if self.fields:
            embed_dict['fields'] = self.fields
        if self.footer:
            embed_dict['footer'] = {'text': self.footer}
        if self.timestamp:
            embed_dict['timestamp'] = self.timestamp
        if self.url:
            embed_dict['url'] = self.url
        if self.thumbnail_url:
            embed_dict['thumbnail'] = {'url': self.thumbnail_url}
        if self.image_url:
            embed_dict['image'] = {'url': self.image_url}
            
        return embed_dict
    
    def to_discord_embed(self) -> Optional[discord.Embed]:
        """Convert to discord.py Embed object."""
        if not DISCORD_PY_AVAILABLE:
            return None
        
        embed = discord.Embed(
            title=self.title,
            description=self.description,
            color=self.color,
            url=self.url
        )
        
        for field_data in self.fields:
            embed.add_field(
                name=field_data.get('name', ''),
                value=field_data.get('value', ''),
                inline=field_data.get('inline', False)
            )
        
        if self.footer:
            embed.set_footer(text=self.footer)
        if self.thumbnail_url:
            embed.set_thumbnail(url=self.thumbnail_url)
        if self.image_url:
            embed.set_image(url=self.image_url)
        if self.timestamp:
            # discord.py will handle timestamp automatically
            pass
            
        return embed


class DiscordBackend(ABC):
    """Abstract base class for Discord notification backends."""
    
    @abstractmethod
    async def send_message(
        self,
        text: Optional[str] = None,
        role_names: Optional[List[str]] = None,
        embed: Optional[DiscordEmbed] = None,
        files: Optional[List[Union[str, Path]]] = None,
        thread_id: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a message via Discord.
        
        Args:
            text: Plain text message content
            role_names: List of role names to mention
            embed: Rich embed object
            files: List of file paths to attach
            thread_id: Thread ID to post to (overrides channel_id)
            channel_id: Channel ID to post to
            
        Returns:
            Dictionary with result status and message info
        """
        pass
    
    @abstractmethod
    async def close(self):
        """Clean up resources."""
        pass


class BotClient(DiscordBackend):
    """
    Discord bot client using discord.py.
    
    Supports full bot features including role mentions, permissions, etc.
    """
    
    def __init__(
        self,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        role_map: Optional[Dict[str, str]] = None
    ):
        """
        Initialize bot client.
        
        Args:
            bot_token: Discord bot token
            guild_id: Discord guild/server ID
            channel_id: Default channel ID
            role_map: Mapping of role names to role IDs
        """
        if not DISCORD_PY_AVAILABLE:
            raise ImportError("discord.py is required for BotClient")
        
        self.bot_token = bot_token
        self.guild_id = guild_id
        self.default_channel_id = channel_id
        self.role_map = role_map or {}
        self.client: Optional[discord.Client] = None
        self._ready = anyio.Event()
        
    async def _initialize_client(self):
        """Initialize the Discord client."""
        if self.client is None:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.guilds = True
            self.client = discord.Client(intents=intents)
            
            @self.client.event
            async def on_ready():
                logger.info(f"Discord bot logged in as {self.client.user}")
                self._ready.set()
            
            # Start the client in the background using anyio
            async with anyio.create_task_group() as tg:
                tg.start_soon(self.client.start, self.bot_token)
                # Wait for ready with timeout
                try:
                    with anyio.fail_after(30.0):
                        await self._ready.wait()
                except TimeoutError:
                    raise RuntimeError("Discord bot failed to connect within 30 seconds")
    
    def _build_role_mentions(self, role_names: Optional[List[str]]) -> str:
        """Build role mention string."""
        if not role_names:
            return ""
        
        mentions = []
        for role_name in role_names:
            role_id = self.role_map.get(role_name)
            if role_id:
                mentions.append(f"<@&{role_id}>")
            else:
                logger.warning(f"Role '{role_name}' not found in role_map")
        
        return " ".join(mentions)
    
    async def send_message(
        self,
        text: Optional[str] = None,
        role_names: Optional[List[str]] = None,
        embed: Optional[DiscordEmbed] = None,
        files: Optional[List[Union[str, Path]]] = None,
        thread_id: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send message using Discord bot."""
        try:
            await self._initialize_client()
            
            # Determine target channel
            target_id = thread_id or channel_id or self.default_channel_id
            channel = self.client.get_channel(int(target_id))
            
            if channel is None:
                return {
                    'status': 'error',
                    'error': f'Channel/thread {target_id} not found'
                }
            
            # Build message content
            content = ""
            if role_names:
                content += self._build_role_mentions(role_names) + " "
            if text:
                content += text
            
            # Prepare embed
            discord_embed = None
            if embed:
                discord_embed = embed.to_discord_embed()
            
            # Prepare files
            discord_files = []
            if files:
                for file_path in files:
                    path = Path(file_path)
                    if path.exists():
                        discord_files.append(discord.File(str(path)))
                    else:
                        logger.warning(f"File not found: {file_path}")
            
            # Send message
            message = await channel.send(
                content=content if content else None,
                embed=discord_embed,
                files=discord_files if discord_files else None
            )
            
            return {
                'status': 'success',
                'message_id': str(message.id),
                'channel_id': str(message.channel.id),
                'timestamp': message.created_at.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error sending Discord message: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def close(self):
        """Close the Discord client."""
        if self.client:
            await self.client.close()


class WebhookClient(DiscordBackend):
    """
    Discord webhook client using aiohttp.
    
    Simpler than bot client but doesn't support role mentions in all server configurations.
    """
    
    def __init__(
        self,
        webhook_url: str,
        role_map: Optional[Dict[str, str]] = None
    ):
        """
        Initialize webhook client.
        
        Args:
            webhook_url: Discord webhook URL
            role_map: Mapping of role names to role IDs (limited support)
        """
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp is required for WebhookClient")
        
        self.webhook_url = webhook_url
        self.role_map = role_map or {}
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def _build_role_mentions(self, role_names: Optional[List[str]]) -> str:
        """Build role mention string (limited functionality with webhooks)."""
        if not role_names:
            return ""
        
        mentions = []
        for role_name in role_names:
            role_id = self.role_map.get(role_name)
            if role_id:
                # Note: Webhooks may not ping roles depending on server settings
                mentions.append(f"<@&{role_id}>")
            else:
                logger.warning(f"Role '{role_name}' not found in role_map")
        
        return " ".join(mentions)
    
    async def send_message(
        self,
        text: Optional[str] = None,
        role_names: Optional[List[str]] = None,
        embed: Optional[DiscordEmbed] = None,
        files: Optional[List[Union[str, Path]]] = None,
        thread_id: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send message using Discord webhook."""
        try:
            session = await self._get_session()
            
            # Build payload
            payload: Dict[str, Any] = {}
            
            # Build content
            content = ""
            if role_names:
                content += self._build_role_mentions(role_names) + " "
            if text:
                content += text
            
            if content:
                payload['content'] = content
            
            # Add embed
            if embed:
                payload['embeds'] = [embed.to_dict()]
            
            # Handle thread_id (webhook query parameter)
            url = self.webhook_url
            if thread_id:
                url += f"?thread_id={thread_id}"
            
            # Send request
            if files:
                # Multipart form data for files
                data = aiohttp.FormData()
                data.add_field('payload_json', json.dumps(payload))
                
                for i, file_path in enumerate(files):
                    path = Path(file_path)
                    if path.exists():
                        data.add_field(
                            f'file{i}',
                            open(path, 'rb'),
                            filename=path.name
                        )
                    else:
                        logger.warning(f"File not found: {file_path}")
                
                async with session.post(url, data=data) as response:
                    response_text = await response.text()
                    if response.status not in (200, 204):
                        return {
                            'status': 'error',
                            'error': f'HTTP {response.status}: {response_text}'
                        }
            else:
                # JSON payload
                async with session.post(url, json=payload) as response:
                    response_text = await response.text()
                    if response.status not in (200, 204):
                        return {
                            'status': 'error',
                            'error': f'HTTP {response.status}: {response_text}'
                        }
            
            return {
                'status': 'success',
                'message': 'Message sent via webhook'
            }
            
        except Exception as e:
            logger.error(f"Error sending webhook message: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e)
            }
    
    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()


class DiscordNotifier:
    """
    Unified Discord notifier that works with both bot and webhook backends.
    
    Configuration can be provided via:
    1. Direct initialization parameters
    2. Environment variables
    3. YAML configuration file
    """
    
    def __init__(
        self,
        mode: str = "webhook",
        bot_token: Optional[str] = None,
        guild_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        webhook_url: Optional[str] = None,
        role_map: Optional[Dict[str, str]] = None,
        config_file: Optional[Union[str, Path]] = None
    ):
        """
        Initialize Discord notifier.
        
        Args:
            mode: "bot" or "webhook"
            bot_token: Discord bot token (for bot mode)
            guild_id: Discord guild ID (for bot mode)
            channel_id: Default channel ID (for bot mode)
            webhook_url: Discord webhook URL (for webhook mode)
            role_map: Mapping of role names to role IDs
            config_file: Path to YAML config file
        """
        self.mode = mode
        self.backend: Optional[DiscordBackend] = None
        
        # Load configuration
        config = self._load_config(
            mode, bot_token, guild_id, channel_id, webhook_url, role_map, config_file
        )
        
        # Initialize backend
        if config['mode'] == 'bot':
            self.backend = BotClient(
                bot_token=config['bot_token'],
                guild_id=config['guild_id'],
                channel_id=config['channel_id'],
                role_map=config.get('role_map', {})
            )
        elif config['mode'] == 'webhook':
            self.backend = WebhookClient(
                webhook_url=config['webhook_url'],
                role_map=config.get('role_map', {})
            )
        else:
            raise ValueError(f"Invalid mode: {config['mode']}")
    
    def _load_config(
        self,
        mode: str,
        bot_token: Optional[str],
        guild_id: Optional[str],
        channel_id: Optional[str],
        webhook_url: Optional[str],
        role_map: Optional[Dict[str, str]],
        config_file: Optional[Union[str, Path]]
    ) -> Dict[str, Any]:
        """Load configuration from various sources."""
        config: Dict[str, Any] = {
            'mode': mode or os.environ.get('DISCORD_MODE', 'webhook')
        }
        
        # Load from config file if provided
        if config_file:
            try:
                import yaml
                with open(config_file, 'r') as f:
                    file_config = yaml.safe_load(f)
                    config.update(file_config)
            except Exception as e:
                logger.warning(f"Could not load config file: {e}")
        
        # Override with explicit parameters
        if bot_token:
            config['bot_token'] = bot_token
        elif 'bot_token' not in config:
            config['bot_token'] = os.environ.get('DISCORD_BOT_TOKEN')
        
        if guild_id:
            config['guild_id'] = guild_id
        elif 'guild_id' not in config:
            config['guild_id'] = os.environ.get('DISCORD_GUILD_ID')
        
        if channel_id:
            config['channel_id'] = channel_id
        elif 'channel_id' not in config:
            config['channel_id'] = os.environ.get('DISCORD_CHANNEL_ID')
        
        if webhook_url:
            config['webhook_url'] = webhook_url
        elif 'webhook_url' not in config:
            config['webhook_url'] = os.environ.get('DISCORD_WEBHOOK_URL')
        
        if role_map:
            config['role_map'] = role_map
        elif 'role_map' not in config:
            # Try to load from env as JSON
            role_map_str = os.environ.get('DISCORD_ROLE_MAP')
            if role_map_str:
                try:
                    config['role_map'] = json.loads(role_map_str)
                except json.JSONDecodeError:
                    logger.warning("Invalid DISCORD_ROLE_MAP JSON")
                    config['role_map'] = {}
        
        return config
    
    async def send_message(
        self,
        text: Optional[str] = None,
        role_names: Optional[List[str]] = None,
        embed: Optional[DiscordEmbed] = None,
        files: Optional[List[Union[str, Path]]] = None,
        thread_id: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send a Discord message.
        
        Args:
            text: Plain text message
            role_names: List of role names to mention
            embed: Rich embed object
            files: List of file paths to attach
            thread_id: Thread ID to post to
            channel_id: Channel ID to post to
            
        Returns:
            Dictionary with status and message info
        """
        if not self.backend:
            return {
                'status': 'error',
                'error': 'Backend not initialized'
            }
        
        return await self.backend.send_message(
            text=text,
            role_names=role_names,
            embed=embed,
            files=files,
            thread_id=thread_id,
            channel_id=channel_id
        )
    
    async def close(self):
        """Clean up resources."""
        if self.backend:
            await self.backend.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
