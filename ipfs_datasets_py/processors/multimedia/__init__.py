"""
Multimedia processing library for IPFS Datasets Python.

This module provides comprehensive multimedia processing capabilities including:
- Video and audio downloading (yt-dlp)
- Media format conversion (FFmpeg)
- Discord chat export and analysis
- Email processing and ingestion (IMAP/POP3/.eml)
- Media analysis and metadata extraction
- Streaming and transcoding
- Batch processing of multimedia content

The library integrates with IPFS for decentralized storage and provides
optimized workflows for content processing and distribution.
"""

from .ytdlp_wrapper import YtDlpWrapper
from .ffmpeg_wrapper import FFmpegWrapper

# Import MediaProcessor conditionally (requires pydantic)
try:
    from .media_processor import MediaProcessor
    HAVE_MEDIA_PROCESSOR = True
except ImportError:
    HAVE_MEDIA_PROCESSOR = False
    MediaProcessor = None

from .media_utils import MediaUtils

# Import Discord wrapper (new addition)
try:
    from .discord_wrapper import DiscordWrapper, create_discord_wrapper
    HAVE_DISCORD = True
except ImportError:
    HAVE_DISCORD = False
    DiscordWrapper = None
    create_discord_wrapper = None

# Import Email processor
try:
    from .email_processor import EmailProcessor, create_email_processor
    HAVE_EMAIL = True
except ImportError:
    HAVE_EMAIL = False
    EmailProcessor = None
    create_email_processor = None

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
    "DiscordWrapper",
    "create_discord_wrapper",
    "EmailProcessor",
    "create_email_processor",
    "HAVE_YTDLP",
    "HAVE_FFMPEG",
    "HAVE_DISCORD",
    "HAVE_EMAIL",
    "HAVE_MEDIA_PROCESSOR"
]
