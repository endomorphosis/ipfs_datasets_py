# ipfs_datasets_py/mcp_server/tools/discord_tools/discord_export.py
"""
Discord export tools for the MCP server.

This tool provides Discord channel, server, and DM export capabilities
using DiscordChatExporter through the MCP protocol.

Supports secure token management via:
- Direct token parameter
- DISCORD_TOKEN environment variable
- Credential manager integration (future)
"""
import asyncio
import os
from typing import Dict, Any, Optional, Union, List
from pathlib import Path

from ipfs_datasets_py.mcp_server.logger import logger

# Import Discord wrapper
try:
    from ipfs_datasets_py.multimedia.discord_wrapper import create_discord_wrapper
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    logger.warning("Discord wrapper not available")


async def discord_export_channel(
    channel_id: str,
    token: Optional[str] = None,
    output_path: Optional[str] = None,
    format: str = "Json",
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    filter_text: Optional[str] = None,
    download_media: bool = False,
    reuse_media: bool = False,
    partition_limit: Optional[str] = None
) -> Dict[str, Any]:
    """
    Export a Discord channel to a file.
    
    Args:
        channel_id: Discord channel ID to export
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        output_path: Output file path (auto-generated if not provided)
        format: Export format: 'HtmlDark', 'HtmlLight', 'Json', 'Csv', 'PlainText'
        after_date: Export messages after this date (ISO format)
        before_date: Export messages before this date (ISO format)
        filter_text: Message filter expression (e.g., "from:username has:image")
        download_media: Download media assets (avatars, attachments, etc.)
        reuse_media: Reuse previously downloaded media
        partition_limit: Split export into parts (e.g., "100" messages or "20mb")
        
    Returns:
        Dict containing export results:
            - status: 'success' or 'error'
            - channel_id: Channel ID
            - output_path: Path to exported file
            - format: Export format used
            - export_time: Time taken for export
            - message_count: Number of messages (if available)
            - error: Error message if failed
    
    Example:
        >>> result = await discord_export_channel(
        ...     channel_id="123456789",
        ...     format="Json"
        ... )
    
    Note:
        Token can be provided via:
        1. Direct token parameter
        2. DISCORD_TOKEN environment variable
        3. Future: Credential manager integration
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available. Ensure discord_wrapper.py is installed.",
                "tool": "discord_export_channel"
            }
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
        # Validate inputs
        if not channel_id or not channel_id.strip():
            return {
                "status": "error",
                "error": "channel_id is required",
                "channel_id": channel_id
            }
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required",
                "channel_id": channel_id
            }
        
        logger.info(f"Exporting Discord channel: {channel_id}")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token, format=format)
        
        # Export channel
        result = await wrapper.export_channel(
            channel_id=channel_id,
            output_path=output_path,
            format=format,
            after=after_date,
            before=before_date,
            filter_text=filter_text,
            download_media=download_media,
            reuse_media=reuse_media,
            partition_limit=partition_limit
        )
        
        logger.info(f"Channel export completed: {result.get('status')}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to export Discord channel {channel_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "channel_id": channel_id,
            "tool": "discord_export_channel"
        }


async def discord_export_guild(
    guild_id: str,
    token: Optional[str] = None,
    output_dir: Optional[str] = None,
    format: str = "Json",
    include_threads: str = "none",
    include_vc: bool = True
) -> Dict[str, Any]:
    """
    Export all channels in a Discord server (guild).
    
    Args:
        guild_id: Discord server (guild) ID to export
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        output_dir: Output directory (auto-generated if not provided)
        format: Export format: 'HtmlDark', 'HtmlLight', 'Json', 'Csv', 'PlainText'
        include_threads: Thread inclusion: 'none', 'active', or 'all'
        include_vc: Include voice channels in export
        
    Returns:
        Dict containing export results
    
    Note:
        Token can be provided via parameter or DISCORD_TOKEN environment variable
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_export_guild"
            }
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
        # Validate inputs
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
        
        # Validate include_threads parameter
        if include_threads not in ['none', 'active', 'all']:
            return {
                "status": "error",
                "error": f"Invalid include_threads value: {include_threads}. Must be 'none', 'active', or 'all'",
                "guild_id": guild_id
            }
        
        logger.info(f"Exporting Discord guild: {guild_id}")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token, format=format)
        
        # Export guild
        result = await wrapper.export_guild(
            guild_id=guild_id,
            output_dir=output_dir,
            format=format,
            include_threads=include_threads,
            include_vc=include_vc
        )
        
        logger.info(f"Guild export completed: {result.get('status')}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to export Discord guild {guild_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "guild_id": guild_id,
            "tool": "discord_export_guild"
        }


async def discord_export_all_channels(
    token: Optional[str] = None,
    output_dir: Optional[str] = None,
    format: str = "Json",
    include_dm: bool = True
) -> Dict[str, Any]:
    """
    Export all accessible Discord channels and DMs.
    
    Args:
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        output_dir: Output directory (auto-generated if not provided)
        format: Export format: 'HtmlDark', 'HtmlLight', 'Json', 'Csv', 'PlainText'
        include_dm: Include direct messages in export
        
    Returns:
        Dict containing export results
    
    Note:
        Token can be provided via parameter or DISCORD_TOKEN environment variable
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_export_all_channels"
            }
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required"
            }
        
        logger.info("Exporting all accessible Discord channels")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token, format=format)
        
        # Export all
        result = await wrapper.export_all(
            output_dir=output_dir,
            format=format,
            include_dm=include_dm
        )
        
        logger.info(f"All channels export completed: {result.get('status')}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to export all Discord channels: {e}")
        return {
            "status": "error",
            "error": str(e),
            "tool": "discord_export_all_channels"
        }


async def discord_export_dm_channels(
    token: Optional[str] = None,
    output_dir: Optional[str] = None,
    format: str = "Json"
) -> Dict[str, Any]:
    """
    Export all direct message channels using native exportdm command.
    
    This uses the DiscordChatExporter's native `exportdm` command which is
    more efficient than exporting DMs individually. Exports all accessible
    DM conversations in one operation.
    
    Args:
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        output_dir: Output directory (auto-generated if not provided)
        format: Export format: 'HtmlDark', 'HtmlLight', 'Json', 'Csv', 'PlainText'
        
    Returns:
        Dict containing export results:
            - status: 'success' or 'error'
            - output_dir: Output directory path
            - dm_channels_exported: Number of DM channels exported
            - export_time: Total export time
            - error: Error message if failed
    
    Example:
        >>> result = await discord_export_dm_channels(format="Json")
    
    Note:
        This is more efficient than manually exporting each DM channel individually.
        Token can be provided via parameter or DISCORD_TOKEN environment variable.
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_export_dm_channels"
            }
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required"
            }
        
        logger.info("Exporting all Discord DM channels using native exportdm")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token, format=format)
        
        # Use the new export_dm method
        result = await wrapper.export_dm(
            output_dir=output_dir,
            format=format
        )
        
        logger.info(f"DM export completed: {result.get('status')}")
        return result
        
    except Exception as e:
        logger.error(f"Failed to export Discord DM channels: {e}")
        return {
            "status": "error",
            "error": str(e),
            "tool": "discord_export_dm_channels"
        }


async def discord_export_dm_channels_individual(
    token: Optional[str] = None,
    output_dir: Optional[str] = None,
    format: str = "Json"
) -> Dict[str, Any]:
    """
    Export all direct message channels by exporting each DM individually.
    
    This is the old implementation that exports each DM channel separately.
    Use `discord_export_dm_channels` for the more efficient native exportdm method.
    
    Args:
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        output_dir: Output directory (auto-generated if not provided)
        format: Export format: 'HtmlDark', 'HtmlLight', 'Json', 'Csv', 'PlainText'
        
    Returns:
        Dict containing export results
    
    Note:
        Consider using `discord_export_dm_channels` instead for better performance.
        Token can be provided via parameter or DISCORD_TOKEN environment variable.
    """
    try:
        if not DISCORD_AVAILABLE:
            return {
                "status": "error",
                "error": "Discord wrapper not available",
                "tool": "discord_export_dm_channels"
            }
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required"
            }
        
        logger.info("Exporting all Discord DM channels")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token, format=format)
        
        # First, list DM channels
        dm_list_result = await wrapper.list_dm_channels()
        
        if dm_list_result['status'] != 'success':
            return dm_list_result
        
        # Export each DM channel
        dm_channels = dm_list_result.get('channels', [])
        results = []
        
        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
        
        for dm_channel in dm_channels:
            channel_id = dm_channel['id']
            channel_name = dm_channel['name']
            
            # Generate output path
            if output_dir:
                ext = wrapper._get_format_extension(format)
                safe_name = "".join(c for c in channel_name if c.isalnum() or c in (' ', '-', '_')).strip()
                dm_output = output_path / f"dm_{safe_name}_{channel_id}.{ext}"
            else:
                dm_output = None
            
            result = await wrapper.export_channel(
                channel_id=channel_id,
                output_path=str(dm_output) if dm_output else None,
                format=format
            )
            results.append(result)
        
        # Aggregate results
        successful = sum(1 for r in results if r.get('status') == 'success')
        failed = len(results) - successful
        
        return {
            "status": "success" if failed == 0 else "partial",
            "output_dir": output_dir,
            "dm_channels_exported": successful,
            "dm_channels_failed": failed,
            "total_dm_channels": len(dm_channels),
            "details": results,
            "tool": "discord_export_dm_channels"
        }
        
    except Exception as e:
        logger.error(f"Failed to export Discord DM channels: {e}")
        return {
            "status": "error",
            "error": str(e),
            "tool": "discord_export_dm_channels"
        }
