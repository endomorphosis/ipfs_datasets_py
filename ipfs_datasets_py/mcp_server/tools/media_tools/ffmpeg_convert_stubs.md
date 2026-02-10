# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_convert.py'

Files last updated: 1751408933.7564564

Stub file last updated: 2025-07-07 01:10:14

## ffmpeg_convert

```python
async def ffmpeg_convert(input_file: Union[str, Dict[str, Any]], output_file: str, output_format: Optional[str] = None, video_codec: Optional[str] = None, audio_codec: Optional[str] = None, video_bitrate: Optional[str] = None, audio_bitrate: Optional[str] = None, resolution: Optional[str] = None, framerate: Optional[str] = None, quality: Optional[str] = None, preset: Optional[str] = None, custom_args: Optional[List[str]] = None, timeout: int = 600) -> Dict[str, Any]:
    """
    Convert media files between different formats using FFmpeg.

This tool supports comprehensive media conversion including:
- Video format conversion (MP4, AVI, MOV, MKV, etc.)
- Audio format conversion (MP3, AAC, FLAC, WAV, etc.)
- Codec transcoding (H.264, H.265, VP9, etc.)
- Quality and compression settings
- Resolution and frame rate changes

Args:
    input_file: Input media file path or dataset containing file paths
    output_file: Output file path
    output_format: Output format (mp4, avi, mov, mkv, mp3, etc.)
    video_codec: Video codec (libx264, libx265, libvpx-vp9, etc.)
    audio_codec: Audio codec (aac, mp3, libflac, pcm_s16le, etc.)
    video_bitrate: Video bitrate (e.g., '1000k', '2M')
    audio_bitrate: Audio bitrate (e.g., '128k', '320k')
    resolution: Output resolution (e.g., '1920x1080', '1280x720')
    framerate: Output frame rate (e.g., '30', '60', '23.976')
    quality: Quality setting (e.g., 'high', 'medium', 'low' or CRF value)
    preset: Encoding preset (ultrafast, fast, medium, slow, veryslow)
    custom_args: Additional custom FFmpeg arguments
    timeout: Processing timeout in seconds
    
Returns:
    Dict containing conversion results and metadata
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
