# Multimedia - Advanced Media Processing and Integration

This module provides comprehensive multimedia processing capabilities for video, audio, and media content within the IPFS Datasets Python library.

## Overview

The multimedia module offers advanced media processing, format conversion, content analysis, and streaming capabilities. It integrates popular tools like FFmpeg and yt-dlp with IPFS storage for decentralized media distribution and processing workflows.

## Components

### FFmpegWrapper (`ffmpeg_wrapper.py`)
Comprehensive FFmpeg integration for video and audio processing.

**Key Features:**
- Video format conversion and transcoding
- Audio extraction and processing
- Frame extraction and image processing
- Streaming and real-time processing
- Batch media processing with progress tracking
- Quality optimization and compression

**Main Methods:**
- `convert_video()` - Convert between video formats
- `extract_audio()` - Extract audio tracks from video
- `extract_frames()` - Extract frames at specified intervals
- `get_media_info()` - Analyze media file properties
- `create_thumbnail()` - Generate video thumbnails

### YtDlpWrapper (`ytdlp_wrapper.py`)
YouTube and web video downloading with metadata extraction.

**Capabilities:**
- Download videos from YouTube and 1000+ other sites
- Format selection and quality optimization
- Metadata extraction (title, description, tags)
- Playlist and channel processing
- Custom output naming and organization
- Progress tracking and error handling

**Main Methods:**
- `download_video()` - Download single videos
- `download_playlist()` - Process entire playlists
- `get_video_info()` - Extract metadata without downloading
- `list_formats()` - Show available quality options

### MediaProcessor (`media_processor.py`)
High-level media processing orchestrator combining multiple tools.

**Processing Workflows:**
- End-to-end video processing pipelines
- Batch processing with worker pools
- Quality assessment and optimization
- Metadata enrichment and standardization
- Integration with IPFS storage
- Processing queue management

### MediaUtils (`media_utils.py`)
Utility functions and helpers for media operations.

**Utility Features:**
- File format detection and validation
- Media property analysis
- Timestamp and duration calculations
- Quality metrics assessment
- Error handling and recovery
- Progress reporting and logging

### File Conversion Systems (Git Submodules)

Two comprehensive file conversion systems are available as git submodules for converting arbitrary file types to text for GraphRAG and knowledge graph generation:

#### omni_converter_mk2 (Submodule)
Advanced multi-format file converter with comprehensive format support.

**Location:** `ipfs_datasets_py/multimedia/omni_converter_mk2/`  
**Repository:** https://github.com/endomorphosis/omni_converter_mk2

**Key Features:**
- 100% format coverage across 25+ file types
- Text, Image, Audio, Video, and Application format support
- Batch processing with parallel execution
- Resource management with configurable limits
- Security validation for all processed files
- Comprehensive metadata extraction
- CLI and Python API interfaces

**Supported Formats:**
- **Text:** HTML, XML, Plain Text, CSV, iCal
- **Image:** JPEG, PNG, GIF, WebP, SVG
- **Audio:** MP3, WAV, OGG, FLAC, AAC
- **Video:** MP4, WebM, AVI, MKV, MOV
- **Application:** PDF, JSON, DOCX, XLSX, ZIP

#### convert_to_txt_based_on_mime_type (Submodule)
Lightweight, production-ready MIME-based file converter with async support.

**Location:** `ipfs_datasets_py/multimedia/convert_to_txt_based_on_mime_type/`  
**Repository:** https://github.com/endomorphosis/convert_to_txt_based_on_mime_type

**Key Features:**
- 96+ MIME types support via MarkItDown integration
- Async/await native implementation
- Stream-based processing for memory efficiency
- Functional programming with error monads
- URL and web file support
- Azure AI Document Intelligence integration
- Designed as library/utility (not standalone)

**Recommended For:**
- GraphRAG document processing
- Knowledge graph generation from arbitrary files
- Web-scale file conversion from URLs
- Real-time document pipelines
- Memory-efficient batch processing

**See Also:** [File Conversion Systems Analysis](../../docs/FILE_CONVERSION_SYSTEMS_ANALYSIS.md) for comprehensive comparison and integration recommendations.

### DiscordWrapper (`discord_wrapper.py`)
Discord chat history export and analysis with DiscordChatExporter integration.

**Capabilities:**
- Export chat histories from Discord channels, servers (guilds), and DMs
- Multiple export formats: JSON, HTML (Dark/Light), CSV, PlainText
- Media asset downloading (attachments, avatars, emojis)
- Date range filtering and message content filtering
- Thread export support (active and archived threads)
- Automatic pagination and rate limit handling
- Chat data analysis (user activity, content patterns, temporal analysis)

**Main Methods:**
- `list_guilds()` - List all accessible Discord servers
- `list_channels()` - List channels in a specific server
- `list_dm_channels()` - List all direct message conversations
- `export_channel()` - Export a single channel's history
- `export_guild()` - Export all channels in a server
- `export_all()` - Export all accessible channels and DMs

**Key Features:**
- **Cross-Platform Support**: Automatic binary installation for Linux, macOS, Windows (x64, arm64, arm)
- **Format Options**: JSON for analysis, HTML for archives, CSV for data processing, PlainText for search
- **Advanced Filtering**: Message filters (from:user, has:image, mentions:user, etc.)
- **Media Handling**: Download and organize message attachments, user avatars, custom emojis
- **Thread Support**: Export both active and archived threads with parent channel context
- **Partition Support**: Split large exports by message count or file size
- **Progress Tracking**: Monitor export progress for long-running operations

## Usage Examples

### Video Processing
```python
from ipfs_datasets_py.multimedia import FFmpegWrapper

ffmpeg = FFmpegWrapper()

# Convert video format
await ffmpeg.convert_video(
    input_path="input.mp4",
    output_path="output.webm",
    quality="high",
    codec="vp9"
)

# Extract frames for analysis
frames = await ffmpeg.extract_frames(
    video_path="video.mp4",
    fps=1.0,
    output_format="jpg"
)
```

### Content Downloading
```python
from ipfs_datasets_py.multimedia import YtDlpWrapper

downloader = YtDlpWrapper()

# Download single video
result = await downloader.download_video(
    url="https://youtube.com/watch?v=example",
    quality="720p",
    output_dir="downloads/"
)

# Process playlist
playlist_results = await downloader.download_playlist(
    url="https://youtube.com/playlist?list=example",
    max_videos=10
)
```

### Batch Media Processing
```python
from ipfs_datasets_py.multimedia import MediaProcessor

processor = MediaProcessor(
    max_workers=4,
    temp_dir="/tmp/media_processing"
)

# Process multiple files
results = await processor.process_batch(
    input_files=media_file_list,
    operations=[
        {"type": "convert", "format": "mp4", "quality": "720p"},
        {"type": "extract_audio", "format": "mp3"},
        {"type": "generate_thumbnail"}
    ]
)
```

### Media Analysis
```python
from ipfs_datasets_py.multimedia import MediaUtils

utils = MediaUtils()

# Analyze media properties
info = utils.analyze_media(
    file_path="video.mp4",
    include_technical=True,
    include_quality_metrics=True
)

print(f"Duration: {info.duration}")
print(f"Resolution: {info.width}x{info.height}")
print(f"Quality score: {info.quality_score}")
```

### Discord Chat Export
```python
from ipfs_datasets_py.multimedia import DiscordWrapper
import asyncio

async def export_discord_data():
    # Initialize wrapper with Discord token
    wrapper = DiscordWrapper(
        token="YOUR_DISCORD_TOKEN",
        default_format="Json",
        default_output_dir="/exports/discord"
    )
    
    # List all accessible servers
    guilds = await wrapper.list_guilds()
    print(f"Found {guilds['count']} servers")
    
    # Export a specific channel
    result = await wrapper.export_channel(
        channel_id="123456789",
        format="Json",
        download_media=True,  # Download attachments
        after="2024-01-01",   # Messages after this date
        filter_text="from:username has:image"  # Optional filtering
    )
    
    print(f"Exported to: {result['output_path']}")
    
    # Export entire server
    server_result = await wrapper.export_guild(
        guild_id="987654321",
        include_threads="all",  # Include all threads
        include_vc=True         # Include voice channels
    )
    
    print(f"Exported {server_result['channels_exported']} channels")

asyncio.run(export_discord_data())
```

### File Conversion for GraphRAG
```python
from ipfs_datasets_py.multimedia.convert_to_txt_based_on_mime_type import (
    FileUnit,
    file_converter
)
from ipfs_datasets_py.rag import GraphRAG
import asyncio

async def convert_files_for_graphrag():
    # Initialize GraphRAG system
    graph = GraphRAG()
    
    # Convert a single file
    file_unit = FileUnit(file_path="document.pdf")
    converted = await file_converter(file_unit)
    text_content = converted.data
    
    # Process with GraphRAG
    embeddings = await graph.process_document(text_content)
    print(f"Generated {len(embeddings)} embeddings")
    
    # Batch convert multiple files
    file_paths = [
        "report.docx",
        "presentation.pptx",
        "data.xlsx",
        "article.html"
    ]
    
    for file_path in file_paths:
        file_unit = FileUnit(file_path=file_path)
        converted = await file_converter(file_unit)
        await graph.add_document(converted.data, metadata={"source": file_path})
    
    # Query the knowledge graph
    results = await graph.query("What are the main findings?")
    print(f"Found {len(results)} relevant passages")

asyncio.run(convert_files_for_graphrag())
```

### Discord Data Analysis
```python
from ipfs_datasets_py.mcp_server.tools.discord_tools import (
    discord_analyze_channel,
    discord_analyze_export
)
import asyncio

async def analyze_discord():
    # Analyze a channel (exports automatically)
    analysis = await discord_analyze_channel(
        channel_id="123456789",
        token="YOUR_TOKEN",
        analysis_types=['message_stats', 'user_activity', 'content_patterns']
    )
    
    # Print analysis results
    if analysis['status'] == 'success':
        stats = analysis['analyses']['message_stats']
        print(f"Total messages: {stats['total_messages']}")
        
        activity = analysis['analyses']['user_activity']
        print(f"Active users: {activity['total_users']}")
        print(f"Top user: {activity['most_active_user']}")
    
    # Analyze a previously exported file
    file_analysis = await discord_analyze_export(
        export_path="/exports/discord/channel_123456789.json"
    )

asyncio.run(analyze_discord())
```

## Configuration

### FFmpeg Configuration
```python
ffmpeg_config = {
    "binary_path": "/usr/bin/ffmpeg",
    "temp_dir": "/tmp/ffmpeg",
    "max_parallel": 4,
    "quality_presets": {
        "high": {"crf": 18, "preset": "slow"},
        "medium": {"crf": 23, "preset": "medium"},
        "low": {"crf": 28, "preset": "fast"}
    }
}
```

### Download Configuration
```python
ytdlp_config = {
    "format": "best[height<=720]",
    "output_template": "%(title)s.%(ext)s",
    "extract_info": True,
    "write_subtitles": True,
    "write_description": True,
    "max_downloads": 100
}
```

### Processing Configuration
```python
processor_config = {
    "max_workers": 8,
    "chunk_size": 10,
    "timeout_per_file": 600,
    "retry_attempts": 3,
    "quality_threshold": 0.8
}
```

## Supported Formats

### Video Formats
- **Input**: MP4, AVI, MKV, WebM, MOV, FLV, 3GP
- **Output**: MP4, WebM, AVI, MKV, MOV (optimized for web)

### Audio Formats  
- **Input**: MP3, WAV, FLAC, AAC, OGG, M4A
- **Output**: MP3, WAV, FLAC, AAC (optimized for quality/size)

### Image Formats (from video)
- **Output**: JPG, PNG, WebP, BMP (frame extraction)

### Discord Export Formats
- **JSON**: Machine-readable format for data analysis and processing
- **HTML (Dark/Light)**: Human-readable archives with full formatting and media
- **CSV**: Spreadsheet format for statistical analysis
- **PlainText**: Simple text format for searching and reading

### File Conversion Formats (via Submodules)

**Text Formats:**
- Plain Text (.txt), Markdown (.md), ReStructuredText (.rst)
- HTML (.html, .htm), XML (.xml), LaTeX (.tex)
- CSV (.csv), TSV (.tsv), YAML (.yaml, .yml)
- JSON (.json, .jsonl), TOML (.toml), INI (.ini)
- Source Code (Python, JavaScript, CSS, SQL, etc.)

**Document Formats:**
- PDF (.pdf)
- Microsoft Office: Word (.docx, .doc), Excel (.xlsx, .xls), PowerPoint (.pptx, .ppt)
- OpenDocument: Text (.odt), Spreadsheet (.ods), Presentation (.odp)
- Rich Text Format (.rtf)
- iCal/Calendar (.ics)

**Image Formats:**
- JPEG (.jpg, .jpeg), PNG (.png), GIF (.gif)
- WebP (.webp), SVG (.svg), BMP (.bmp)
- TIFF (.tif, .tiff), AVIF (.avif), APNG (.apng)

**Archive Formats:**
- ZIP (.zip), TAR (.tar), RAR (.rar)
- 7-Zip (.7z), GZip (.gz), BZip2 (.bz2)

**See:** [FILE_CONVERSION_SYSTEMS_ANALYSIS.md](../../docs/FILE_CONVERSION_SYSTEMS_ANALYSIS.md) for complete format list and capabilities.

## Advanced Features

### Quality Optimization
- Adaptive bitrate selection
- Content-aware encoding parameters
- Quality assessment and validation
- Size optimization with quality preservation

### Batch Processing
- Parallel processing with worker pools
- Progress tracking and reporting
- Error recovery and retry logic
- Resource usage optimization

### IPFS Integration
- Direct upload to IPFS after processing
- Content addressing for processed media
- Distributed storage and retrieval
- Metadata preservation and linking

### Streaming Support
- Real-time media processing
- Live stream capture and processing
- Adaptive streaming format generation
- WebRTC integration capabilities

## Performance Optimization

### Hardware Acceleration
- GPU acceleration for encoding/decoding
- Multi-core CPU utilization
- Memory-efficient streaming processing
- Hardware-specific optimization profiles

### Caching Strategies
- Processed media result caching
- Metadata caching for repeated operations
- Temporary file management
- Smart cache invalidation

### Resource Management
- Memory usage monitoring and limiting
- CPU and GPU resource allocation
- Disk space management
- Network bandwidth optimization

## Integration

The multimedia module integrates with:

- **IPFS Storage** - Decentralized media storage and distribution
- **Embeddings** - Generate embeddings from media content
- **Search Module** - Media content search and discovery
- **RAG Module** - Multimedia content in RAG workflows (including arbitrary file conversion for GraphRAG)
- **Knowledge Graphs** - Extract entities and relationships from any file type
- **MCP Tools** - AI assistant access to media processing
- **Audit Module** - Media processing operation logging
- **File Conversion Systems** - Convert arbitrary files to text for AI processing (via submodules)

## Error Handling

### Common Error Scenarios
- Missing media dependencies (FFmpeg, yt-dlp)
- Unsupported format combinations
- Network connectivity issues
- Insufficient disk space or memory
- Corrupted or invalid media files

### Recovery Strategies
- Automatic dependency installation guidance
- Format fallback mechanisms
- Progressive download with retries
- Graceful degradation for partial failures
- Comprehensive error reporting

## Dependencies

### Core Dependencies
- `yt-dlp` - Video downloading and metadata extraction
- `ffmpeg-python` - FFmpeg Python bindings
- `asyncio` - Asynchronous media processing

### Discord Dependencies
- No additional Python dependencies required
- DiscordChatExporter CLI automatically downloaded on first use
- Supports Linux (x64, arm64, arm, musl), macOS (x64, arm64), Windows (x64, x86, arm64)

### Optional Dependencies
- `opencv-python` - Advanced image/video processing
- `pillow` - Image manipulation and optimization
- `mutagen` - Audio metadata processing

### File Conversion Dependencies (Submodules)
- `markitdown` - Microsoft's file-to-markdown converter (convert_to_txt_based_on_mime_type)
- `pydantic` - Data validation (both converters)
- `playwright` - Browser automation for web content (convert_to_txt_based_on_mime_type)
- `azure-ai-documentintelligence` - Cloud AI document processing (convert_to_txt_based_on_mime_type)
- `openai-whisper` - Audio transcription (omni_converter_mk2)
- `pytesseract` - OCR capabilities (omni_converter_mk2)
- `python-docx`, `openpyxl`, `python-pptx` - Office format support (omni_converter_mk2)

### System Dependencies
- `ffmpeg` - Media processing engine (system install)
- `yt-dlp` - Video downloader (pip install)

## Installation Notes

### FFmpeg Installation
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

### Complete Installation
```bash
pip install ipfs-datasets-py[multimedia]
```

## See Also

- **[File Conversion Systems Analysis](../../docs/FILE_CONVERSION_SYSTEMS_ANALYSIS.md)** - Comprehensive comparison of conversion systems
- [Discord Usage Examples](../../docs/discord_usage_examples.md) - Comprehensive Discord integration guide
- [PDF Processing](../pdf_processing/README.md) - Document processing capabilities
- [Utils](../utils/README.md) - Text processing utilities
- [Embeddings](../embeddings/README.md) - Generate embeddings from media content
- [RAG Module](../rag/README.md) - GraphRAG and knowledge graph capabilities
- [IPFS Integration Guide](../../docs/distributed_features.md) - Decentralized storage
- [Performance Guide](../../docs/performance_optimization.md) - Media processing optimization
- [DiscordChatExporter Repository](https://github.com/Tyrrrz/DiscordChatExporter) - Upstream project
- [omni_converter_mk2 Repository](https://github.com/endomorphosis/omni_converter_mk2) - Submodule
- [convert_to_txt_based_on_mime_type Repository](https://github.com/endomorphosis/convert_to_txt_based_on_mime_type) - Submodule