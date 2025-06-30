"""
Multimedia processing library for IPFS Datasets Python.

This module provides comprehensive multimedia processing capabilities including:
- Video and audio downloading (yt-dlp)
- Media format conversion (FFmpeg)
- Media analysis and metadata extraction
- Streaming and transcoding
- Batch processing of multimedia content

The library integrates with IPFS for decentralized storage and provides
optimized workflows for content processing and distribution.
"""

from .ytdlp_wrapper import YtDlpWrapper
from .ffmpeg_wrapper import FFmpegWrapper
from .media_processor import MediaProcessor
from .media_utils import MediaUtils

# Feature availability flags
try:
    import yt_dlp
    HAVE_YTDLP = True
except ImportError:
    HAVE_YTDLP = False

try:
    import ffmpeg
    HAVE_FFMPEG = True
except ImportError:
    HAVE_FFMPEG = False

__all__ = [
    "YtDlpWrapper",
    "FFmpegWrapper", 
    "MediaProcessor",
    "MediaUtils",
    "HAVE_YTDLP",
    "HAVE_FFMPEG"
]
