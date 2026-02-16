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
