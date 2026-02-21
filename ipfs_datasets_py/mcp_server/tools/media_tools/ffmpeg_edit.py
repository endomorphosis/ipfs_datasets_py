# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_edit.py
"""
FFmpeg editing MCP Tool — thin wrapper.

Business logic: ipfs_datasets_py.processors.multimedia.ffmpeg_edit_engine
"""

from ipfs_datasets_py.processors.multimedia.ffmpeg_edit_engine import (  # noqa: F401
    ffmpeg_cut,
    ffmpeg_splice,
    ffmpeg_concat,
)

__all__ = [
    "ffmpeg_cut",
    "ffmpeg_splice",
    "ffmpeg_concat",
]
