"""FFmpeg filters tool — thin MCP shim.

All business logic lives in:
    ipfs_datasets_py.processors.multimedia.ffmpeg_filters_engine
"""

from ipfs_datasets_py.processors.multimedia.ffmpeg_filters_engine import (  # noqa: F401
    ffmpeg_apply_filters,
    get_available_filters,
)

__all__ = ["ffmpeg_apply_filters", "get_available_filters"]
