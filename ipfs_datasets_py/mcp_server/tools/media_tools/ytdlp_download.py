# ipfs_datasets_py/mcp_server/tools/media_tools/ytdlp_download.py
"""YT-DLP download tools (thin MCP wrapper).

Business logic lives in ipfs_datasets_py.processors.multimedia.ytdlp_download_engine.
"""
from __future__ import annotations

from ipfs_datasets_py.processors.multimedia.ytdlp_download_engine import (  # noqa: F401
    ytdlp_batch_download,
    ytdlp_download_playlist,
    ytdlp_download_video,
    ytdlp_extract_info,
    ytdlp_search_videos,
)

__all__ = [
    "ytdlp_download_video",
    "ytdlp_download_playlist",
    "ytdlp_extract_info",
    "ytdlp_search_videos",
    "ytdlp_batch_download",
]
