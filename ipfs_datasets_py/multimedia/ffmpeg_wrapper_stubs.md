# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/multimedia/ffmpeg_wrapper.py'

Files last updated: 1751434989.4752653

Stub file last updated: 2025-07-07 02:00:56

## FFmpegWrapper

```python
class FFmpegWrapper:
    """
    Wrapper class for FFmpeg functionality with async support.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, default_output_dir: Optional[str] = None, enable_logging: bool = True):
    """
    Initialize FFmpeg wrapper.

Args:
    default_output_dir: Default directory for output files
    enable_logging: Enable detailed logging
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegWrapper

## convert_video

```python
async def convert_video(self, input_path: str, output_path: str, **kwargs) -> Dict[str, Any]:
    """
    Convert video format using FFmpeg.

Args:
    input_path: Input video file path
    output_path: Output video file path
    **kwargs: Additional FFmpeg options
    
Returns:
    Dict containing conversion results
    """
```
* **Async:** True
* **Method:** True
* **Class:** FFmpegWrapper

## is_available

```python
def is_available(self) -> bool:
    """
    Check if FFmpeg is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FFmpegWrapper
