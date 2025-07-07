# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_filters.py'

Files last updated: 1751408933.7564564

Stub file last updated: 2025-07-07 01:10:14

## ffmpeg_apply_filters

```python
async def ffmpeg_apply_filters(input_file: Union[str, Dict[str, Any]], output_file: str, video_filters: Optional[List[str]] = None, audio_filters: Optional[List[str]] = None, filter_complex: Optional[str] = None, output_format: Optional[str] = None, preserve_metadata: bool = True, timeout: int = 600) -> Dict[str, Any]:
    """
    Apply video and audio filters to media files using FFmpeg.

This tool supports comprehensive filter application including:
- Video filters (scale, crop, rotate, blur, sharpen, etc.)
- Audio filters (volume, equalizer, noise reduction, etc.)
- Complex filter graphs for advanced processing
- Filter chains for sequential processing
- Real-time filter preview and application

Args:
    input_file: Input media file path or dataset containing file paths
    output_file: Output file path
    video_filters: List of video filter strings (e.g., ['scale=1280:720', 'blur=1'])
    audio_filters: List of audio filter strings (e.g., ['volume=0.5', 'highpass=f=200'])
    filter_complex: Complex filter graph string for advanced processing
    output_format: Output format (inferred from extension if not provided)
    preserve_metadata: Whether to preserve original metadata
    timeout: Maximum execution time in seconds
    
Returns:
    Dict containing:
    - status: "success" or "error"
    - input_file: Path to input file
    - output_file: Path to output file
    - filters_applied: List of filters that were applied
    - duration: Processing duration in seconds
    - file_size_before: Input file size in bytes
    - file_size_after: Output file size in bytes
    - message: Success/error message
    - command: FFmpeg command used (for debugging)
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_available_filters

```python
async def get_available_filters() -> Dict[str, Any]:
    """
    Get list of available FFmpeg filters.

Returns:
    Dict containing:
    - status: "success" or "error"
    - video_filters: List of available video filters
    - audio_filters: List of available audio filters
    - filter_count: Total number of filters
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
