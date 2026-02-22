"""Discord processing package — canonical domain module.

Provides core Discord data analysis and export capabilities.

Usage::

    from ipfs_datasets_py.processors.discord import (
        discord_analyze_channel,
        discord_analyze_guild,
        discord_analyze_export,
        discord_export_channel,
        discord_export_guild,
        discord_export_all_channels,
    )
"""
from __future__ import annotations

try:
    from .discord_analysis_engine import (
        discord_analyze_channel,
        discord_analyze_export,
        discord_analyze_guild,
    )
except Exception:
    discord_analyze_channel = None  # type: ignore[assignment]
    discord_analyze_guild = None  # type: ignore[assignment]
    discord_analyze_export = None  # type: ignore[assignment]

try:
    from .discord_export_engine import (
        discord_export_all_channels,
        discord_export_channel,
        discord_export_dm_channels,
        discord_export_dm_channels_individual,
        discord_export_guild,
    )
except Exception:
    discord_export_channel = None  # type: ignore[assignment]
    discord_export_guild = None  # type: ignore[assignment]
    discord_export_all_channels = None  # type: ignore[assignment]
    discord_export_dm_channels = None  # type: ignore[assignment]
    discord_export_dm_channels_individual = None  # type: ignore[assignment]

__all__ = [
    "discord_analyze_channel",
    "discord_analyze_guild",
    "discord_analyze_export",
    "discord_export_channel",
    "discord_export_guild",
    "discord_export_all_channels",
    "discord_export_dm_channels",
    "discord_export_dm_channels_individual",
]

try:
    from .discord_convert_engine import (
        discord_convert_export,
        discord_batch_convert_exports,
    )
except Exception:
    discord_convert_export = None  # type: ignore[assignment]
    discord_batch_convert_exports = None  # type: ignore[assignment]

__all__ += [
    "discord_convert_export",
    "discord_batch_convert_exports",
]
