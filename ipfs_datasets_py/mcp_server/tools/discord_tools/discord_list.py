# ipfs_datasets_py/mcp_server/tools/discord_tools/discord_list.py
"""
Discord listing tools for the MCP server.

This tool provides Discord server, channel, and DM listing capabilities.
"""
import asyncio
from typing import Dict, Any, Optional

from ipfs_datasets_py.mcp_server.logger import logger

# Import Discord wrapper
try:
    from ipfs_datasets_py.multimedia.discord_wrapper import create_discord_wrapper
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    logger.warning("Discord wrapper not available")


async def discord_list_guilds(token: str) -> Dict[str, Any]:
    """
    List all accessible Discord servers (guilds).
    
    Args:
        token: Discord bot or user token for authentication
        
    Returns:
        Dict containing:
            - status: 'success' or 'error'
            - guilds: List of guild information with id and name
            - count: Number of guilds
            - error: Error message if failed
    
    Example:
        >>> result = await discord_list_guilds(token="YOUR_TOKEN")
        >>> for guild in result['guilds']:
        ...     print(f"{guild['id']}: {guild['name']}")
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_list_guilds"
            }
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required"
            }
        
        logger.info("Listing Discord guilds")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token)
        
        # List guilds
        result = await wrapper.list_guilds()
        
        logger.info(f"Found {result.get('count', 0)} guilds")
        return result
        
    except Exception as e:
        logger.error(f"Failed to list Discord guilds: {e}")
        return {
            "status": "error",
            "error": str(e),
            "guilds": [],
            "count": 0,
            "tool": "discord_list_guilds"
        }


async def discord_list_channels(
    guild_id: str,
    token: str
) -> Dict[str, Any]:
    """
    List all channels in a specific Discord server (guild).
    
    Args:
        guild_id: Discord server (guild) ID
        token: Discord bot or user token for authentication
        
    Returns:
        Dict containing:
            - status: 'success' or 'error'
            - guild_id: Guild ID
            - channels: List of channel information with id, category, and name
            - count: Number of channels
            - error: Error message if failed
    
    Example:
        >>> result = await discord_list_channels(
        ...     guild_id="987654321",
        ...     token="YOUR_TOKEN"
        ... )
        >>> for channel in result['channels']:
        ...     print(f"{channel['name']} (Category: {channel['category']})")
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_list_channels"
            }
        
        if not guild_id or not guild_id.strip():
            return {
                "status": "error",
                "error": "guild_id is required",
                "guild_id": guild_id
            }
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required",
                "guild_id": guild_id
            }
        
        logger.info(f"Listing channels for guild: {guild_id}")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token)
        
        # List channels
        result = await wrapper.list_channels(guild_id=guild_id)
        
        logger.info(f"Found {result.get('count', 0)} channels in guild {guild_id}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to list channels for guild {guild_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "guild_id": guild_id,
            "channels": [],
            "count": 0,
            "tool": "discord_list_channels"
        }


async def discord_list_dm_channels(token: str) -> Dict[str, Any]:
    """
    List all direct message channels.
    
    Args:
        token: Discord bot or user token for authentication
        
    Returns:
        Dict containing:
            - status: 'success' or 'error'
            - channels: List of DM channel information with id and name
            - count: Number of DM channels
            - error: Error message if failed
    
    Example:
        >>> result = await discord_list_dm_channels(token="YOUR_TOKEN")
        >>> for dm in result['channels']:
        ...     print(f"{dm['id']}: {dm['name']}")
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_list_dm_channels"
            }
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required"
            }
        
        logger.info("Listing Discord DM channels")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token)
        
        # List DM channels
        result = await wrapper.list_dm_channels()
        
        logger.info(f"Found {result.get('count', 0)} DM channels")
        return result
        
    except Exception as e:
        logger.error(f"Failed to list Discord DM channels: {e}")
        return {
            "status": "error",
            "error": str(e),
            "channels": [],
            "count": 0,
            "tool": "discord_list_dm_channels"
        }
