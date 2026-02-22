"""FFmpeg batch processing tool — thin MCP shim.

All business logic lives in:
    ipfs_datasets_py.processors.multimedia.ffmpeg_batch_engine
"""

from ipfs_datasets_py.processors.multimedia.ffmpeg_batch_engine import (  # noqa: F401
    ffmpeg_batch_process,
    get_batch_status,
)

__all__ = ["ffmpeg_batch_process", "get_batch_status"]
