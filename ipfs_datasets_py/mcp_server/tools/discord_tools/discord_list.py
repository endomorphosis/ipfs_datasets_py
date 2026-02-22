# ipfs_datasets_py/mcp_server/tools/discord_tools/discord_list.py
"""
Discord listing tools for the MCP server.

This tool provides Discord server, channel, and DM listing capabilities.

Supports secure token management via:
- Direct token parameter
- DISCORD_TOKEN environment variable

Uses anyio for asyncio/trio compatibility (libp2p integration)
"""
import anyio
import os
from typing import Dict, Any, Optional

import logging

logger = logging.getLogger(__name__)

# Import Discord wrapper
try:
    from ipfs_datasets_py.processors.multimedia.discord_wrapper import create_discord_wrapper
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    logger.warning("Discord wrapper not available")


async def discord_list_guilds(token: Optional[str] = None) -> Dict[str, Any]:
    """
    List all accessible Discord servers (guilds).
    
    Args:
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        
    Returns:
        Dict containing:
            - status: 'success' or 'error'
            - guilds: List of guild information with id and name
            - count: Number of guilds
            - error: Error message if failed
    
    Example:
        >>> result = await discord_list_guilds()
        >>> for guild in result['guilds']:
        ...     print(f"{guild['id']}: {guild['name']}")
    
    Note:
        Token can be provided via parameter or DISCORD_TOKEN environment variable
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_list_guilds"
            }
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
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
            "error": "Failed to list Discord guilds due to an internal error.",
            "guilds": [],
            "count": 0,
            "tool": "discord_list_guilds"
        }


async def discord_list_channels(
    guild_id: str,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    List all channels in a specific Discord server (guild).
    
    Args:
        guild_id: Discord server (guild) ID
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        
    Returns:
        Dict containing channel list
    
    Note:
        Token can be provided via parameter or DISCORD_TOKEN environment variable
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_list_channels"
            }
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
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


async def discord_list_dm_channels(token: Optional[str] = None) -> Dict[str, Any]:
    """
    List all direct message channels.
    
    Args:
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        
    Returns:
        Dict containing DM channel list
    
    Note:
        Token can be provided via parameter or DISCORD_TOKEN environment variable
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_list_dm_channels"
            }
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
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
            "error": "Failed to list Discord DM channels due to an internal error.",
            "channels": [],
            "count": 0,
            "tool": "discord_list_dm_channels"
        }
