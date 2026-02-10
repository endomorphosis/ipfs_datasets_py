# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_mux_demux.py'

Files last updated: 1751408933.7564564

Stub file last updated: 2025-07-07 01:10:14

## ffmpeg_demux

```python
async def ffmpeg_demux(input_file: Union[str, Dict[str, Any]], output_dir: str, extract_video: bool = True, extract_audio: bool = True, extract_subtitles: bool = True, video_format: str = "mp4", audio_format: str = "mp3", subtitle_format: str = "srt", stream_selection: Optional[Dict[str, List[int]]] = None, timeout: int = 300) -> Dict[str, Any]:
    """
    Demux (separate) streams from a media container into separate files.

This tool extracts:
- Video streams to separate video files
- Audio streams to separate audio files (multiple languages/tracks)
- Subtitle streams to separate subtitle files

Args:
    input_file: Input media file path or dataset
    output_dir: Output directory for extracted streams
    extract_video: Whether to extract video streams
    extract_audio: Whether to extract audio streams
    extract_subtitles: Whether to extract subtitle streams
    video_format: Output format for video streams
    audio_format: Output format for audio streams
    subtitle_format: Output format for subtitle streams
    stream_selection: Specific streams to extract (e.g., {'video': [0], 'audio': [0, 1]})
    timeout: Processing timeout in seconds
    
Returns:
    Dict containing demuxing results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ffmpeg_mux

```python
async def ffmpeg_mux(video_input: Optional[str] = None, audio_inputs: Optional[List[str]] = None, subtitle_inputs: Optional[List[str]] = None, output_file: str = "", output_format: Optional[str] = None, video_codec: str = "copy", audio_codec: str = "copy", subtitle_codec: str = "copy", map_streams: Optional[List[str]] = None, metadata: Optional[Dict[str, str]] = None, timeout: int = 300) -> Dict[str, Any]:
    """
    Mux (combine) separate video, audio, and subtitle streams into a single container.

This tool allows combining:
- Video stream from one file
- Multiple audio streams (different languages, commentary tracks)
- Multiple subtitle streams
- Custom stream mapping and metadata

Args:
    video_input: Path to video file
    audio_inputs: List of paths to audio files
    subtitle_inputs: List of paths to subtitle files
    output_file: Output file path
    output_format: Output container format
    video_codec: Video codec ('copy' to avoid re-encoding)
    audio_codec: Audio codec ('copy' to avoid re-encoding)
    subtitle_codec: Subtitle codec ('copy' to avoid re-encoding)
    map_streams: Custom stream mapping (e.g., ['0:v:0', '1:a:0'])
    metadata: Metadata to add to output file
    timeout: Processing timeout in seconds
    
Returns:
    Dict containing muxing results
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
