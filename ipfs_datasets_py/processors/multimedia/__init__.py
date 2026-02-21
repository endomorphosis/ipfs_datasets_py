"""
Multimedia processing library for IPFS Datasets Python.

This module provides comprehensive multimedia processing capabilities including:
- Video and audio downloading (yt-dlp wrapper for 1000+ sites)
- Media format conversion (FFmpeg wrapper for transcoding)
- File format conversion (omni_converter_mk2 for text extraction)
- Discord chat export and analysis
- Email processing and ingestion (IMAP/POP3/.eml)
- Media analysis and metadata extraction
- Streaming and transcoding
- Batch processing of multimedia content

The library integrates with IPFS for decentralized storage and provides
optimized workflows for content processing and distribution.

## Quick Start

### Video Downloading
```python
from ipfs_datasets_py.processors.multimedia import YtDlpWrapper

ytdlp = YtDlpWrapper()
info = ytdlp.download_video("https://youtube.com/watch?v=...")
```

### Media Processing
```python
from ipfs_datasets_py.processors.multimedia import FFmpegWrapper

ffmpeg = FFmpegWrapper()
ffmpeg.convert_video("input.mp4", "output.webm")
```

### File Conversion (Text Extraction)
```python
from ipfs_datasets_py.processors.multimedia import UnifiedConverter

converter = UnifiedConverter()
result = converter.convert_file("document.pdf")
if result.success:
    print(result.text)
else:
    print(f"Conversion failed: {result.error}")
```

**Note:** UnifiedConverter currently has stub adapters. For production use,
use the underlying converters directly:
- `omni_converter_mk2/` for modern format conversion
- `convert_to_txt_based_on_mime_type/` for legacy async conversion

## Architecture

This module provides three layers:
1. **Root Processors** (production-ready): YtDlpWrapper, FFmpegWrapper, MediaProcessor
2. **omni_converter_mk2** (342 files, git submodule): Modern plugin-based converter
3. **convert_to_txt** (102 files, git submodule): Legacy async converter

See docs/MULTIMEDIA_ARCHITECTURE_ANALYSIS.md for detailed architecture documentation.
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

# Import unified converter interface (Phase 9C)
# Note: Adapters are currently stubs - set to False until implemented
try:
    from .converters import UnifiedConverter, ConverterRegistry
    # Converters exist but adapters are stubs - mark as unavailable
    HAVE_CONVERTERS = False
except ImportError:
    HAVE_CONVERTERS = False
    UnifiedConverter = None
    ConverterRegistry = None

# Canonical FFmpeg editing/info engine functions
from .ffmpeg_edit_engine import ffmpeg_cut, ffmpeg_splice, ffmpeg_concat  # noqa: E402
from .ffmpeg_info_engine import ffmpeg_probe, ffmpeg_analyze  # noqa: E402
# Canonical FFmpeg mux/demux, filters, stream, batch engines
from .ffmpeg_mux_demux_engine import ffmpeg_mux, ffmpeg_demux  # noqa: E402
from .ffmpeg_filters_engine import ffmpeg_apply_filters, get_available_filters  # noqa: E402
from .ffmpeg_stream_engine import ffmpeg_stream_input, ffmpeg_stream_output  # noqa: E402
from .ffmpeg_batch_engine import ffmpeg_batch_process, get_batch_status  # noqa: E402

__all__ = [
    # Root processors (production-ready)
    "YtDlpWrapper",
    "FFmpegWrapper",
    "MediaProcessor",
    "MediaUtils",
    "DiscordWrapper",
    "create_discord_wrapper",
    "EmailProcessor",
    "create_email_processor",
    # Canonical FFmpeg engines
    "ffmpeg_cut",
    "ffmpeg_splice",
    "ffmpeg_concat",
    "ffmpeg_probe",
    "ffmpeg_analyze",
    "ffmpeg_mux",
    "ffmpeg_demux",
    "ffmpeg_apply_filters",
    "get_available_filters",
    "ffmpeg_stream_input",
    "ffmpeg_stream_output",
    "ffmpeg_batch_process",
    "get_batch_status",
    # Unified converter interface (Phase 9C)
    "UnifiedConverter",
    "ConverterRegistry",
    # Feature flags
    "HAVE_YTDLP",
    "HAVE_FFMPEG",
    "HAVE_DISCORD",
    "HAVE_EMAIL",
    "HAVE_MEDIA_PROCESSOR",
    "HAVE_CONVERTERS"
]

from .ytdlp_download_engine import (
    ytdlp_download_video,
    ytdlp_download_playlist,
    ytdlp_extract_info,
    ytdlp_search_videos,
    ytdlp_batch_download,
)

try:
    from .email_analyze_engine import (
        email_analyze_export,
        email_search_export,
    )
except Exception:
    email_analyze_export = None  # type: ignore[assignment]
    email_search_export = None  # type: ignore[assignment]
