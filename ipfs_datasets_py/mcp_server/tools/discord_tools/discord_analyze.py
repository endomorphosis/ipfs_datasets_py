"""Discord analysis tools — thin MCP wrapper.

All domain logic lives at:
  ipfs_datasets_py.processors.discord.discord_analysis_engine
"""
from ipfs_datasets_py.processors.discord.discord_analysis_engine import (  # noqa: F401
    _analyze_content_patterns,
    _analyze_message_stats,
    _analyze_time_patterns,
    _analyze_user_activity,
    discord_analyze_channel,
    discord_analyze_export,
    discord_analyze_guild,
)

__all__ = [
    "discord_analyze_channel",
    "discord_analyze_guild",
    "discord_analyze_export",
    "_analyze_message_stats",
    "_analyze_user_activity",
    "_analyze_content_patterns",
    "_analyze_time_patterns",
]
