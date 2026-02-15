# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/processors/by_ability/_video_processor.py'

Files last updated: 1748487709.3493063

Stub file last updated: 2025-07-17 05:45:32

## VideoProcessor

```python
class VideoProcessor:
    """
    Processor for video files.

Extracts thumbnails, frames, and information from video files using
memory-efficient approaches.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
    """
    Initialize the video processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VideoProcessor

## _extract_thumbnail_cv2

```python
def _extract_thumbnail_cv2(self, file_path: str, time_offset: float, max_size: int) -> Optional[bytes]:
    """
    Extract thumbnail using OpenCV (fallback method).

Args:
    file_path: Path to the video file.
    time_offset: Time in seconds to extract thumbnail from.
    max_size: Maximum thumbnail dimension.
    
Returns:
    Thumbnail as bytes in PNG format, or None if extraction failed.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VideoProcessor

## can_process

```python
def can_process(self, format_name: str) -> bool:
    """
    Check if the processor can handle the given format.

Args:
    format_name: The format to check.
    
Returns:
    True if the format is supported, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VideoProcessor

## extract_frame_at_time

```python
def extract_frame_at_time(self, file_path: str, time_position: float, options: Optional[dict[str, Any]] = None) -> Optional[bytes]:
    """
    Extract a specific frame at a given time position.

Args:
    file_path: Path to the video file.
    time_position: Time in seconds to extract frame from.
    options: Extraction options.
    
Returns:
    Frame as bytes in PNG format, or None if extraction failed.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VideoProcessor

## extract_key_frames

```python
def extract_key_frames(self, file_path: str, options: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """
    Extract multiple key frames from a video at regular intervals.
Uses memory-efficient streaming approach to avoid loading entire video.

Args:
    file_path: Path to the video file.
    options: Extraction options including:
        - frame_count: Number of frames to extract (default: 5).
        - max_size: Maximum frame dimension (default: 320).
        
Returns:
    List of dictionaries containing frame data and timestamps.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VideoProcessor

## extract_thumbnail

```python
def extract_thumbnail(self, file_path: str, options: Optional[dict[str, Any]] = None) -> Optional[bytes]:
    """
    Extract a thumbnail from a video file using memory-efficient methods.

Args:
    file_path: Path to the video file.
    options: Extraction options including:
        - time_offset: Time in seconds to extract thumbnail from (default: 5).
        - max_size: Maximum thumbnail dimension (default: 320).
        
Returns:
    Thumbnail as bytes in PNG format, or None if extraction failed.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VideoProcessor

## extract_video_info

```python
def extract_video_info(self, file_path: str) -> dict[str, Any]:
    """
    Extract video information using ffprobe.
Uses a memory-efficient approach to avoid loading the entire file.

Args:
    file_path: Path to the video file.
    
Returns:
    Dictionary with video information including:
        - duration: Video duration in seconds.
        - width: Video width in pixels.
        - height: Video height in pixels.
        - codec: Video codec name.
        - fps: Frames per second.
        - bitrate: Video bitrate.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VideoProcessor

## supported_formats

```python
@property
def supported_formats(self) -> list[str]:
    """
    Get the list of formats supported by this processor.
# TODO Add in support to check if ffmpeg is installed.

Returns:
    A list of format names supported by this processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** VideoProcessor
