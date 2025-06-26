# ipfs_datasets_py/mcp_server/tools/media_tools/__init__.py
"""
Media processing tools for the MCP server using FFmpeg.

These tools provide comprehensive audio/visual data processing capabilities
including conversion, muxing, demuxing, streaming, ingestion, splicing, cutting,
and concatenation of media files through FFmpeg integration.
"""

# Import only the main tool functions, not utility classes or exceptions
from .ffmpeg_convert import ffmpeg_convert
from .ffmpeg_mux_demux import ffmpeg_mux, ffmpeg_demux
from .ffmpeg_stream import ffmpeg_stream_input, ffmpeg_stream_output
from .ffmpeg_edit import ffmpeg_cut, ffmpeg_splice, ffmpeg_concat
from .ffmpeg_info import ffmpeg_probe, ffmpeg_analyze
from .ffmpeg_filters import ffmpeg_apply_filters
from .ffmpeg_batch import ffmpeg_batch_process

__all__ = [
    "ffmpeg_convert",
    "ffmpeg_mux",
    "ffmpeg_demux", 
    "ffmpeg_stream_input",
    "ffmpeg_stream_output",
    "ffmpeg_cut",
    "ffmpeg_splice",
    "ffmpeg_concat",
    "ffmpeg_probe",
    "ffmpeg_analyze",
    "ffmpeg_apply_filters",
    "ffmpeg_batch_process"
]
