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
- **RAG Module** - Multimedia content in RAG workflows
- **MCP Tools** - AI assistant access to media processing
- **Audit Module** - Media processing operation logging

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

### Optional Dependencies
- `opencv-python` - Advanced image/video processing
- `pillow` - Image manipulation and optimization
- `mutagen` - Audio metadata processing

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

- [PDF Processing](../pdf_processing/README.md) - Document processing capabilities
- [Utils](../utils/README.md) - Text processing utilities
- [Embeddings](../embeddings/README.md) - Generate embeddings from media content
- [IPFS Integration Guide](../../docs/distributed_features.md) - Decentralized storage
- [Performance Guide](../../docs/performance_optimization.md) - Media processing optimization