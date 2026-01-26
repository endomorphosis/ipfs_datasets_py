# ipfs_datasets_py/mcp_server/tools/discord_tools/discord_analyze.py
"""
Discord analysis tools for the MCP server.

This tool provides Discord chat data analysis capabilities including
message statistics, user activity, and content analysis.

Supports secure token management via:
- Direct token parameter
- DISCORD_TOKEN environment variable
"""
import json
import os
from typing import Dict, Any, Optional, List
from pathlib import Path
from collections import Counter
from datetime import datetime

from ipfs_datasets_py.mcp_server.logger import logger


async def discord_analyze_channel(
    channel_id: str,
    token: Optional[str] = None,
    analysis_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Analyze a Discord channel's activity and content.
    
    This function first exports the channel data in JSON format, then
    performs various analyses on the exported data.
    
    Args:
        channel_id: Discord channel ID to analyze
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        analysis_types: Types of analysis to perform:
            - 'message_stats': Message count, date ranges
            - 'user_activity': Message counts per user
            - 'content_patterns': Common words, emojis, mentions
            - 'time_patterns': Activity by hour/day
            Default is all analyses.
        
    Returns:
        Dict containing analysis results
    
    Note:
        Token can be provided via parameter or DISCORD_TOKEN environment variable
    """
    try:
        # Import here to avoid circular dependency
        from ipfs_datasets_py.multimedia.discord_wrapper import create_discord_wrapper
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required",
                "channel_id": channel_id
            }
        
        # Set default analysis types
        if analysis_types is None:
            analysis_types = ['message_stats', 'user_activity', 'content_patterns']
        
        logger.info(f"Analyzing Discord channel: {channel_id}")
        
        # Create wrapper and export channel data
        wrapper = create_discord_wrapper(token=token, format='Json')
        
        # Export to temporary JSON file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_file:
            tmp_path = tmp_file.name
        
        export_result = await wrapper.export_channel(
            channel_id=channel_id,
            output_path=tmp_path,
            format='Json'
        )
        
        if export_result['status'] != 'success':
            return {
                "status": "error",
                "error": f"Failed to export channel: {export_result.get('error')}",
                "channel_id": channel_id
            }
        
        # Load and analyze the exported data
        analyses = {}
        
        try:
            with open(tmp_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            messages = data.get('messages', [])
            
            if 'message_stats' in analysis_types:
                analyses['message_stats'] = _analyze_message_stats(messages)
            
            if 'user_activity' in analysis_types:
                analyses['user_activity'] = _analyze_user_activity(messages)
            
            if 'content_patterns' in analysis_types:
                analyses['content_patterns'] = _analyze_content_patterns(messages)
            
            if 'time_patterns' in analysis_types:
                analyses['time_patterns'] = _analyze_time_patterns(messages)
            
            # Clean up temporary file
            Path(tmp_path).unlink(missing_ok=True)
            
            return {
                "status": "success",
                "channel_id": channel_id,
                "analyses": analyses,
                "message_count": len(messages)
            }
            
        except Exception as e:
            # Clean up temporary file on error
            Path(tmp_path).unlink(missing_ok=True)
            raise e
        
    except Exception as e:
        logger.error(f"Failed to analyze Discord channel {channel_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "channel_id": channel_id,
            "tool": "discord_analyze_channel"
        }


async def discord_analyze_guild(
    guild_id: str,
    token: Optional[str] = None,
    summary_only: bool = True
) -> Dict[str, Any]:
    """
    Analyze a Discord server (guild)'s overall activity.
    
    Args:
        guild_id: Discord server (guild) ID to analyze
        token: Discord bot or user token. If not provided, uses DISCORD_TOKEN environment variable.
        summary_only: If True, only return summary statistics without
            detailed channel-by-channel analysis
        
    Returns:
        Dict containing guild analysis results
    
    Note:
        Token can be provided via parameter or DISCORD_TOKEN environment variable
    """
    try:
        from ipfs_datasets_py.multimedia.discord_wrapper import create_discord_wrapper
        
        # Use environment variable if token not provided
        token = token or os.environ.get('DISCORD_TOKEN')
        
        if not token or not token.strip():
            return {
                "status": "error",
                "error": "Discord token is required",
                "guild_id": guild_id
            }
        
        logger.info(f"Analyzing Discord guild: {guild_id}")
        
        # Create wrapper
        wrapper = create_discord_wrapper(token=token)
        
        # List channels in guild
        channels_result = await wrapper.list_channels(guild_id=guild_id)
        
        if channels_result['status'] != 'success':
            return {
                "status": "error",
                "error": f"Failed to list channels: {channels_result.get('error')}",
                "guild_id": guild_id
            }
        
        channels = channels_result.get('channels', [])
        
        if summary_only:
            # Return just summary info
            return {
                "status": "success",
                "guild_id": guild_id,
                "channel_count": len(channels),
                "channels": channels,
                "summary": {
                    "total_channels": len(channels),
                    "categories": list(set(ch.get('category', 'Unknown') for ch in channels))
                }
            }
        else:
            # Analyze each channel (this could take a while)
            channel_analyses = []
            for channel in channels:
                analysis = await discord_analyze_channel(
                    channel_id=channel['id'],
                    token=token,
                    analysis_types=['message_stats']
                )
                channel_analyses.append({
                    'channel': channel,
                    'analysis': analysis
                })
            
            return {
                "status": "success",
                "guild_id": guild_id,
                "channel_count": len(channels),
                "channels": channel_analyses
            }
        
    except Exception as e:
        logger.error(f"Failed to analyze Discord guild {guild_id}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "guild_id": guild_id,
            "tool": "discord_analyze_guild"
        }


async def discord_analyze_export(
    export_path: str,
    analysis_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Analyze a previously exported Discord chat file.
    
    Args:
        export_path: Path to exported Discord JSON file
        analysis_types: Types of analysis to perform (see discord_analyze_channel)
        
    Returns:
        Dict containing analysis results:
            - status: 'success' or 'error'
            - export_path: Path to analyzed file
            - analyses: Dict of analysis results
            - message_count: Total messages analyzed
            - error: Error message if failed
    
    Example:
        >>> result = await discord_analyze_export(
        ...     export_path="/exports/channel_123456789.json"
        ... )
    """
    try:
        # Determine base directory for Discord exports
        base_dir_env = os.environ.get("DISCORD_EXPORT_BASE_DIR")
        
        # Validate the user-provided export_path before using it
        if not export_path or not isinstance(export_path, str):
            return {
                "status": "error",
                "error": "Invalid export path",
                "export_path": export_path,
            }

        export_path_obj = Path(export_path)

        # If DISCORD_EXPORT_BASE_DIR is set, enforce path confinement
        if base_dir_env:
            base_dir = Path(base_dir_env).resolve()
            
            # Reject absolute paths when base_dir is configured
            if export_path_obj.is_absolute():
                # Allow absolute paths if they resolve inside base_dir
                resolved_export = export_path_obj.resolve()
                try:
                    resolved_export.relative_to(base_dir)
                except ValueError:
                    return {
                        "status": "error",
                        "error": f"Absolute export paths must be within {base_dir}",
                        "export_path": export_path,
                    }
                export_file = resolved_export
            else:
                # Build the full path relative to the base directory
                export_file = (base_dir / export_path_obj).resolve()
        else:
            # No base_dir configured: allow absolute paths directly
            if export_path_obj.is_absolute():
                export_file = export_path_obj.resolve()
            else:
                # Relative path: resolve from current directory
                export_file = Path.cwd() / export_path_obj
                export_file = export_file.resolve()

        # Ensure the resolved path is within the allowed base directory (if configured)
        if base_dir_env:
            try:
                export_file.relative_to(base_dir)
            except ValueError:
                return {
                    "status": "error",
                    "error": "Export path is not within the allowed base directory",
                    "export_path": export_path
                }
        
        if not export_file.is_file():
            return {
                "status": "error",
                "error": f"Export file not found: {export_path}",
                "export_path": export_path
            }
        
        # Set default analysis types
        if analysis_types is None:
            analysis_types = ['message_stats', 'user_activity', 'content_patterns']
        
        logger.info(f"Analyzing Discord export: {export_path}")
        
        # Load exported data
        try:
            with open(export_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return {
                "status": "error",
                "error": f"JSON parse error: {e}",
                "export_path": export_path,
                "tool": "discord_analyze_export",
            }
        
        messages = data.get('messages', [])
        
        # Perform analyses
        analyses = {}
        
        if 'message_stats' in analysis_types:
            analyses['message_stats'] = _analyze_message_stats(messages)
        
        if 'user_activity' in analysis_types:
            analyses['user_activity'] = _analyze_user_activity(messages)
        
        if 'content_patterns' in analysis_types:
            analyses['content_patterns'] = _analyze_content_patterns(messages)
        
        if 'time_patterns' in analysis_types:
            analyses['time_patterns'] = _analyze_time_patterns(messages)
        
        return {
            "status": "success",
            "export_path": export_path,
            "analyses": analyses,
            "message_count": len(messages)
        }
        
    except Exception as e:
        logger.error(f"Failed to analyze Discord export {export_path}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "export_path": export_path,
            "tool": "discord_analyze_export"
        }


# Helper functions for analysis

def _analyze_message_stats(messages: List[Dict]) -> Dict[str, Any]:
    """Analyze basic message statistics."""
    if not messages:
        return {
            "total_messages": 0,
            "date_range": None
        }
    
    dates = [msg.get('timestamp') for msg in messages if msg.get('timestamp')]
    
    return {
        "total_messages": len(messages),
        "date_range": {
            "earliest": min(dates) if dates else None,
            "latest": max(dates) if dates else None
        },
        "messages_with_attachments": sum(1 for m in messages if m.get('attachments')),
        "messages_with_embeds": sum(1 for m in messages if m.get('embeds'))
    }


def _analyze_user_activity(messages: List[Dict]) -> Dict[str, Any]:
    """Analyze user activity patterns."""
    if not messages:
        return {"user_message_counts": {}, "total_users": 0}
    
    user_counts = Counter()
    for msg in messages:
        author = msg.get('author', {})
        user_id = author.get('id', 'unknown')
        user_name = author.get('name', 'Unknown')
        user_counts[f"{user_name} ({user_id})"] += 1
    
    return {
        "user_message_counts": dict(user_counts.most_common(20)),  # Top 20 users
        "total_users": len(user_counts),
        "most_active_user": user_counts.most_common(1)[0] if user_counts else None
    }


def _analyze_content_patterns(messages: List[Dict]) -> Dict[str, Any]:
    """Analyze content patterns in messages."""
    if not messages:
        return {}
    
    all_text = " ".join(msg.get('content', '') for msg in messages)
    words = all_text.lower().split()
    
    # Count common words (excluding very short words)
    word_counts = Counter(w for w in words if len(w) > 3)
    
    # Count mentions
    mention_counts = sum(1 for msg in messages if '@' in msg.get('content', ''))
    
    # Count reactions (if available)
    reaction_counts = sum(len(msg.get('reactions', [])) for msg in messages)
    
    return {
        "common_words": dict(word_counts.most_common(20)),
        "total_words": len(words),
        "unique_words": len(set(words)),
        "messages_with_mentions": mention_counts,
        "total_reactions": reaction_counts
    }


def _analyze_time_patterns(messages: List[Dict]) -> Dict[str, Any]:
    """Analyze temporal patterns in messages."""
    if not messages:
        return {}
    
    hour_counts = Counter()
    day_counts = Counter()
    
    for msg in messages:
        timestamp = msg.get('timestamp')
        if timestamp:
            try:
                # Parse ISO timestamp
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                hour_counts[dt.hour] += 1
                day_counts[dt.strftime('%A')] += 1
            except:
                pass
    
    return {
        "messages_by_hour": dict(hour_counts),
        "messages_by_day": dict(day_counts),
        "busiest_hour": hour_counts.most_common(1)[0] if hour_counts else None,
        "busiest_day": day_counts.most_common(1)[0] if day_counts else None
    }
