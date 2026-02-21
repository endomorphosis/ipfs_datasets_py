"""FFmpeg streaming tool — thin MCP shim.

All business logic lives in:
    ipfs_datasets_py.processors.multimedia.ffmpeg_stream_engine
"""

from ipfs_datasets_py.processors.multimedia.ffmpeg_stream_engine import (  # noqa: F401
    ffmpeg_stream_input,
    ffmpeg_stream_output,
)

__all__ = ["ffmpeg_stream_input", "ffmpeg_stream_output"]
