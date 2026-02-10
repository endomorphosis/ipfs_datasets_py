# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/media_tools/ffmpeg_utils.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## FFmpegError

```python
class FFmpegError(Exception):
    """
    Custom exception for FFmpeg-related errors.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FFmpegUtils

```python
class FFmpegUtils:
    """
    Utility class for FFmpeg operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## _find_ffmpeg

```python
def _find_ffmpeg(self) -> str:
    """
    Find FFmpeg executable path.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## _find_ffprobe

```python
def _find_ffprobe(self) -> str:
    """
    Find FFprobe executable path.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## build_common_args

```python
def build_common_args(self, input_file: str, output_file: str, video_codec: Optional[str] = None, audio_codec: Optional[str] = None, video_bitrate: Optional[str] = None, audio_bitrate: Optional[str] = None, resolution: Optional[str] = None, framerate: Optional[str] = None, overwrite: bool = True) -> List[str]:
    """
    Build common FFmpeg arguments.

Args:
    input_file: Input file path
    output_file: Output file path
    video_codec: Video codec (e.g., 'libx264', 'libx265')
    audio_codec: Audio codec (e.g., 'aac', 'mp3')
    video_bitrate: Video bitrate (e.g., '1000k', '2M')
    audio_bitrate: Audio bitrate (e.g., '128k', '320k')
    resolution: Resolution (e.g., '1920x1080', '1280x720')
    framerate: Frame rate (e.g., '30', '60')
    overwrite: Whether to overwrite output file
    
Returns:
    List of FFmpeg arguments
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## format_time

```python
def format_time(self, seconds: float) -> str:
    """
    Format seconds to HH:MM:SS.mmm format.

Args:
    seconds: Time in seconds
    
Returns:
    Formatted time string
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## get_supported_codecs

```python
def get_supported_codecs(self) -> Dict[str, List[str]]:
    """
    Get supported audio and video codecs.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## get_supported_formats

```python
def get_supported_formats(self) -> Dict[str, List[str]]:
    """
    Get supported input and output formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## parse_time_format

```python
def parse_time_format(self, time_str: str) -> float:
    """
    Parse time string to seconds.

Args:
    time_str: Time string (e.g., '00:01:30', '90', '1:30')
    
Returns:
    Time in seconds
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## probe_media_info

```python
async def probe_media_info(self, file_path: str) -> Dict[str, Any]:
    """
    Probe media file for information using FFprobe.

Args:
    file_path: Path to media file
    
Returns:
    Dict with media information
    """
```
* **Async:** True
* **Method:** True
* **Class:** FFmpegUtils

## run_ffmpeg_command

```python
async def run_ffmpeg_command(self, args: List[str], timeout: int = 300, capture_output: bool = True) -> Dict[str, Any]:
    """
    Run FFmpeg command asynchronously.

Args:
    args: Full FFmpeg command arguments (including ffmpeg path)
    timeout: Command timeout in seconds
    capture_output: Whether to capture stdout/stderr
    
Returns:
    Dict with execution results
    """
```
* **Async:** True
* **Method:** True
* **Class:** FFmpegUtils

## validate_input_file

```python
def validate_input_file(self, file_path: str) -> bool:
    """
    Validate input media file exists and is accessible.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils

## validate_output_path

```python
def validate_output_path(self, output_path: str) -> bool:
    """
    Validate output path is writable.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegUtils
