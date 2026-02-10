# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_stream.py'

Files last updated: 1751408933.7564564

Stub file last updated: 2025-07-07 01:10:14

## ffmpeg_stream_input

```python
async def ffmpeg_stream_input(stream_url: str, output_file: str, duration: Optional[str] = None, video_codec: str = "copy", audio_codec: str = "copy", format: Optional[str] = None, buffer_size: Optional[str] = None, timeout: int = 3600) -> Dict[str, Any]:
    """
    Capture/ingest media from streaming sources using FFmpeg.

This tool supports:
- RTMP/RTMPS streams
- HTTP/HTTPS streams
- UDP/RTP streams
- WebRTC streams
- Network cameras (IP cameras)
- Screen capture

Args:
    stream_url: Input stream URL or source
    output_file: Output file path to save the stream
    duration: Recording duration (e.g., '00:10:00' for 10 minutes)
    video_codec: Video codec for encoding ('copy' to avoid re-encoding)
    audio_codec: Audio codec for encoding ('copy' to avoid re-encoding)
    format: Input format hint (optional)
    buffer_size: Input buffer size (e.g., '1M', '512k')
    timeout: Maximum recording timeout in seconds
    
Returns:
    Dict containing stream capture results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ffmpeg_stream_output

```python
async def ffmpeg_stream_output(input_file: Union[str, Dict[str, Any]], stream_url: str, video_codec: str = "libx264", audio_codec: str = "aac", video_bitrate: Optional[str] = None, audio_bitrate: Optional[str] = None, resolution: Optional[str] = None, framerate: Optional[str] = None, format: str = "flv", preset: str = "fast", tune: Optional[str] = None, keyframe_interval: Optional[str] = None, buffer_size: Optional[str] = None, max_muxing_queue_size: str = "1024", timeout: int = 3600) -> Dict[str, Any]:
    """
    Stream media to output destinations using FFmpeg.

This tool supports streaming to:
- RTMP servers (YouTube, Twitch, Facebook Live, etc.)
- RTSP servers
- UDP/RTP destinations
- HTTP/HLS endpoints
- Custom streaming protocols

Args:
    input_file: Input media file path or dataset
    stream_url: Output stream URL or destination
    video_codec: Video codec for streaming
    audio_codec: Audio codec for streaming
    video_bitrate: Video bitrate (e.g., '2500k', '5M')
    audio_bitrate: Audio bitrate (e.g., '128k', '320k')
    resolution: Output resolution (e.g., '1920x1080')
    framerate: Output frame rate (e.g., '30', '60')
    format: Output format (flv, mpegts, etc.)
    preset: Encoding preset for quality/speed balance
    tune: Encoding tune (film, animation, zerolatency)
    keyframe_interval: Keyframe interval in seconds
    buffer_size: Output buffer size
    max_muxing_queue_size: Maximum muxing queue size
    timeout: Streaming timeout in seconds
    
Returns:
    Dict containing streaming results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## main

```python
async def main() -> Dict[str, Any]:
    """
    Main function for MCP tool registration.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
