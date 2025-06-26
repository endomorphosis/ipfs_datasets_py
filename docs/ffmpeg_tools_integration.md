# FFmpeg Tools Integration for IPFS Datasets MCP Server

## Overview

The IPFS Datasets MCP Server now includes a comprehensive suite of FFmpeg-based tools that provide professional-grade audio and video processing capabilities. These tools integrate seamlessly with the Model Context Protocol (MCP) server, enabling AI assistants to perform complex media processing tasks through natural language interactions.

## Features

### 🎬 Media Processing Capabilities

#### Video Processing
- **Format Conversion**: Convert between all FFmpeg-supported formats (MP4, AVI, MOV, MKV, WebM, FLV, etc.)
- **Codec Transcoding**: Support for modern codecs (H.264, H.265/HEVC, VP9, AV1, etc.)
- **Resolution Scaling**: Change video resolution and aspect ratio
- **Frame Rate Conversion**: Adjust frame rates for different playback requirements
- **Quality Control**: Precise control over bitrates, compression, and quality settings

#### Audio Processing
- **Format Conversion**: Convert between audio formats (MP3, AAC, FLAC, WAV, OGG, etc.)
- **Codec Support**: Wide range of audio codecs with quality options
- **Audio Extraction**: Extract audio tracks from video files
- **Bitrate Control**: Adjust audio quality and file size

#### Advanced Operations
- **Muxing/Demuxing**: Combine or separate audio/video/subtitle streams
- **Streaming**: Real-time input capture and output broadcasting
- **Editing**: Cut, splice, and concatenate media files
- **Filters**: Apply video and audio filters and effects
- **Batch Processing**: Process multiple files in parallel with progress tracking

### 🛠️ Tool Architecture

#### Core Components

1. **FFmpeg Utilities (`ffmpeg_utils.py`)**
   - Centralized FFmpeg/FFprobe integration
   - System capability detection
   - Command execution and error handling
   - Path validation and safety checks

2. **Conversion Tool (`ffmpeg_convert.py`)**
   - Universal media format conversion
   - Codec transcoding and quality control
   - Resolution and frame rate adjustments

3. **Mux/Demux Tool (`ffmpeg_mux_demux.py`)**
   - Stream combination and separation
   - Container format handling
   - Metadata preservation

4. **Streaming Tool (`ffmpeg_stream.py`)**
   - Live input capture and processing
   - Real-time output streaming
   - Network protocol support

5. **Editing Tool (`ffmpeg_edit.py`)**
   - Precise cutting and trimming
   - Multi-file splicing and concatenation
   - Frame-accurate editing

6. **Information Tool (`ffmpeg_info.py`)**
   - Comprehensive media file analysis
   - Stream metadata extraction
   - Quality metrics and statistics

7. **Filters Tool (`ffmpeg_filters.py`)**
   - Video filter application (scale, crop, rotate, effects)
   - Audio filter processing (volume, EQ, noise reduction)
   - Complex filter graph support

8. **Batch Processing Tool (`ffmpeg_batch.py`)**
   - Parallel processing of multiple files
   - Progress tracking and resumption
   - Checkpoint/recovery functionality

## Installation and Setup

### Prerequisites

1. **FFmpeg Installation**
   ```bash
   # Ubuntu/Debian
   sudo apt update && sudo apt install ffmpeg
   
   # macOS with Homebrew
   brew install ffmpeg
   
   # Windows with Chocolatey
   choco install ffmpeg
   ```

2. **Verify Installation**
   ```bash
   ffmpeg -version
   ffprobe -version
   ```

### MCP Server Integration

The FFmpeg tools are automatically registered with the MCP server when the media_tools directory is included in the tool discovery process.

```python
# The tools are automatically available through the MCP server
from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

server = IPFSDatasetsMCPServer()
server.register_tools()
# FFmpeg tools are now available: ffmpeg_convert, ffmpeg_mux, etc.
```

## Usage Examples

### 1. Video Format Conversion

Convert an AVI file to MP4 with H.264 codec:

```python
result = await ffmpeg_convert(
    input_file="input_video.avi",
    output_file="output_video.mp4",
    video_codec="libx264",
    audio_codec="aac",
    quality="high"
)
```

### 2. Audio Extraction

Extract audio from a video file:

```python
result = await ffmpeg_convert(
    input_file="video.mp4",
    output_file="audio.mp3", 
    video_codec=None,  # Remove video stream
    audio_codec="mp3",
    audio_bitrate="320k"
)
```

### 3. Video Resolution Scaling

Scale video to 1080p with quality control:

```python
result = await ffmpeg_convert(
    input_file="input.mp4",
    output_file="scaled.mp4",
    resolution="1920x1080",
    video_codec="libx264",
    quality="medium"
)
```

### 4. Apply Video and Audio Filters

```python
result = await ffmpeg_apply_filters(
    input_file="input.mp4",
    output_file="filtered.mp4",
    video_filters=["scale=1280:720", "brightness=0.1", "contrast=1.2"],
    audio_filters=["volume=0.8", "highpass=f=200"]
)
```

### 5. Media File Analysis

Get detailed information about a media file:

```python
result = await ffmpeg_probe(
    input_file="media.mp4",
    show_format=True,
    show_streams=True,
    include_metadata=True
)
```

### 6. Batch Processing

Process multiple files in parallel:

```python
result = await ffmpeg_batch_process(
    input_files=["video1.avi", "video2.mov", "video3.mkv"],
    output_directory="./converted/",
    operation="convert",
    operation_params={
        "video_codec": "libx264",
        "audio_codec": "aac",
        "quality": "high"
    },
    max_parallel=3
)
```

### 7. Stream Muxing

Combine separate video and audio files:

```python
result = await ffmpeg_mux(
    input_files=["video.mp4", "audio.wav"],
    output_file="combined.mp4",
    stream_mapping={"0:v": "video", "1:a": "audio"}
)
```

### 8. Video Cutting and Trimming

Extract a segment from a video:

```python
result = await ffmpeg_cut(
    input_file="long_video.mp4",
    output_file="segment.mp4",
    start_time="00:02:30",
    duration="00:01:45"
)
```

## API Reference

### Common Parameters

Most FFmpeg tools accept these common parameters:

- `input_file`: Path to input media file or dataset containing file paths
- `output_file`: Path where the processed file will be saved
- `timeout`: Maximum execution time in seconds (default: 600)

### Return Format

All tools return a standardized response dictionary:

```python
{
    "status": "success" | "error",
    "input_file": "path/to/input",
    "output_file": "path/to/output", 
    "duration": 15.234,  # Processing time in seconds
    "file_size_before": 1048576,  # Input file size in bytes
    "file_size_after": 524288,   # Output file size in bytes
    "message": "Operation completed successfully",
    "command": "ffmpeg command used",  # For debugging
    # Tool-specific additional fields
}
```

### Error Handling

All tools include comprehensive error handling:

- Input file validation
- Output path accessibility checks
- FFmpeg execution error capture
- Timeout protection
- Detailed error messages and debugging information

## Integration with AI Assistants

### Natural Language Processing

The FFmpeg tools are designed to work seamlessly with AI assistants through the MCP protocol:

**Example AI Interaction:**
```
User: "Convert this video to MP4 and make it 720p"
AI: Uses ffmpeg_convert with resolution="1280x720" and output_format="mp4"

User: "Extract the audio from all these video files"
AI: Uses ffmpeg_batch_process with operation="extract_audio"

User: "Make this video brighter and increase the volume"
AI: Uses ffmpeg_apply_filters with video_filters=["brightness=0.2"] and audio_filters=["volume=1.5"]
```

### Intelligent Parameter Handling

The AI can intelligently map natural language requests to technical parameters:

- Quality levels: "high", "medium", "low" → appropriate bitrates and presets
- Resolutions: "1080p", "720p", "4K" → exact pixel dimensions
- Formats: "MP4", "Web video", "Audio only" → appropriate codecs and containers

## Performance and Optimization

### Parallel Processing

- Batch operations support configurable parallelism
- Automatic resource management and throttling
- Progress tracking and resumption capabilities

### Memory Management

- Streaming processing for large files
- Temporary file cleanup
- Resource usage monitoring

### Quality vs. Speed Trade-offs

- Configurable presets for different use cases
- Hardware acceleration support (when available)
- Adaptive quality settings based on content

## Security and Safety

### Input Validation

- File path sanitization
- Format verification
- Size limit enforcement

### Safe Execution

- Command injection prevention
- Resource usage limits
- Timeout protection

### Error Recovery

- Graceful failure handling
- Partial result preservation
- Detailed error reporting

## Testing and Verification

### Test Suite Coverage

Run the comprehensive test suite:

```bash
python test_ffmpeg_tools.py
```

### Verification Commands

```bash
# Test individual tools
python -c "import asyncio; from ipfs_datasets_py.mcp_server.tools.media_tools.ffmpeg_convert import main; print(asyncio.run(main()))"

# Test MCP server integration
python -c "from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer; s = IPFSDatasetsMCPServer(); s.register_tools(); print(f'Registered {len(s.tools)} tools')"
```

## Troubleshooting

### Common Issues

1. **FFmpeg Not Found**
   - Install FFmpeg system-wide
   - Ensure FFmpeg is in system PATH
   - Verify with `ffmpeg -version`

2. **Permission Errors**
   - Check output directory write permissions
   - Verify input file read permissions

3. **Codec Errors**
   - Check FFmpeg codec support: `ffmpeg -codecs`
   - Use alternative codecs if needed

4. **Performance Issues**
   - Reduce parallel processing threads
   - Use hardware acceleration if available
   - Optimize quality settings

### Debug Mode

Enable detailed logging for troubleshooting:

```python
import logging
logging.getLogger('ipfs_datasets_py.mcp_server.tools.media_tools').setLevel(logging.DEBUG)
```

## Future Enhancements

### Planned Features

- Hardware acceleration integration (GPU processing)
- Advanced filter graph builder
- Real-time streaming dashboard
- Quality analysis and optimization recommendations
- Integration with cloud storage services
- Automated subtitle processing
- Content-aware encoding optimization

### Contribution Guidelines

Contributions to the FFmpeg tools are welcome! Please follow these guidelines:

1. Maintain compatibility with the MCP protocol
2. Include comprehensive documentation and examples
3. Add appropriate test coverage
4. Follow the existing code style and patterns
5. Ensure proper error handling and validation

## Conclusion

The FFmpeg tools integration provides a powerful, professional-grade media processing capability within the IPFS Datasets MCP server. With support for all major audio and video formats, comprehensive editing capabilities, and intelligent AI assistant integration, these tools enable sophisticated media workflows through simple, natural language interactions.

The modular architecture ensures maintainability and extensibility, while the comprehensive error handling and validation provide reliability for production use. Whether processing single files or managing large batch operations, the FFmpeg tools deliver the performance and flexibility needed for modern media processing workflows.
