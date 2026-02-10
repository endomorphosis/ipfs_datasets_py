# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_edit.py'

Files last updated: 1751408933.7564564

Stub file last updated: 2025-07-07 01:10:14

## ffmpeg_concat

```python
async def ffmpeg_concat(input_files: List[Union[str, Dict[str, Any]]], output_file: str, video_codec: str = "copy", audio_codec: str = "copy", method: str = "filter", safe_mode: bool = True, timeout: int = 600) -> Dict[str, Any]:
    """
    Concatenate multiple media files into a single output file.

This tool supports different concatenation methods:
- Filter complex (re-encodes, handles different formats)
- Demuxer concat (fast, requires same format/codec)
- File list concat (intermediate approach)

Args:
    input_files: List of input media files or datasets
    output_file: Output file path
    video_codec: Video codec ('copy' for no re-encoding)
    audio_codec: Audio codec ('copy' for no re-encoding)
    method: Concatenation method ('filter', 'demuxer', 'file_list')
    safe_mode: Enable safe file path handling
    timeout: Processing timeout in seconds
    
Returns:
    Dict containing concatenation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ffmpeg_cut

```python
async def ffmpeg_cut(input_file: Union[str, Dict[str, Any]], output_file: str, start_time: str, end_time: Optional[str] = None, duration: Optional[str] = None, video_codec: str = "copy", audio_codec: str = "copy", accurate_seek: bool = True, timeout: int = 300) -> Dict[str, Any]:
    """
    Cut/trim a segment from a media file using FFmpeg.

This tool allows precise cutting of video and audio segments with:
- Frame-accurate seeking
- Lossless cutting (with copy codecs)
- Time-based or duration-based cutting
- Preservation of original quality

Args:
    input_file: Input media file path or dataset
    output_file: Output file path for the cut segment
    start_time: Start time (e.g., '00:01:30', '90', '1:30')
    end_time: End time (e.g., '00:05:00', '300')
    duration: Duration instead of end time (e.g., '00:02:30', '150')
    video_codec: Video codec ('copy' for lossless, 'libx264' for re-encoding)
    audio_codec: Audio codec ('copy' for lossless, 'aac' for re-encoding)
    accurate_seek: Use accurate but slower seeking
    timeout: Processing timeout in seconds
    
Returns:
    Dict containing cutting results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## ffmpeg_splice

```python
async def ffmpeg_splice(input_files: List[Union[str, Dict[str, Any]]], output_file: str, segments: List[Dict[str, Any]], video_codec: str = "libx264", audio_codec: str = "aac", transition_type: str = "cut", transition_duration: float = 0.0, timeout: int = 600) -> Dict[str, Any]:
    """
    Splice multiple segments from various files into a single output file.

This tool creates complex edits by:
- Extracting specific segments from multiple input files
- Applying transitions between segments
- Maintaining sync between video and audio
- Supporting crossfades and other effects

Args:
    input_files: List of input media files or datasets
    output_file: Output file path
    segments: List of segment definitions with start/end times and source files
    video_codec: Video codec for output
    audio_codec: Audio codec for output
    transition_type: Type of transition ('cut', 'fade', 'crossfade')
    transition_duration: Duration of transitions in seconds
    timeout: Processing timeout in seconds
    
Returns:
    Dict containing splicing results
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
