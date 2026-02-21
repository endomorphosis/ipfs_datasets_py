# ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_info.py
"""
FFmpeg media info MCP Tool — thin wrapper.

Business logic: ipfs_datasets_py.processors.multimedia.ffmpeg_info_engine
"""

from ipfs_datasets_py.processors.multimedia.ffmpeg_info_engine import (  # noqa: F401
    ffmpeg_probe,
    ffmpeg_analyze,
    _analyze_video_quality,
    _analyze_audio_quality,
    _analyze_performance,
    _analyze_compression,
    _generate_analysis_summary,
    _save_analysis_report,
)

__all__ = [
    "ffmpeg_probe",
    "ffmpeg_analyze",
]
