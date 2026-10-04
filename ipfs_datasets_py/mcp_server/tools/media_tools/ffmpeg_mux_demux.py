"""FFmpeg mux/demux tool — thin MCP shim.

All business logic lives in:
    ipfs_datasets_py.processors.multimedia.ffmpeg_mux_demux_engine
"""

from ipfs_datasets_py.processors.multimedia.ffmpeg_mux_demux_engine import (  # noqa: F401
    ffmpeg_mux,
    ffmpeg_demux,
)

__all__ = ["ffmpeg_mux", "ffmpeg_demux"]
