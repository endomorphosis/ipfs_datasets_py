# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/multimedia/media_processor.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 02:00:56

## MediaProcessor

```python
class MediaProcessor:
    """
    Unified media processor that coordinates different multimedia operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, default_output_dir: Optional[str] = None, enable_logging: bool = True):
    """
    Initialize media processor.

Args:
    default_output_dir: Default directory for output files
    enable_logging: Enable detailed logging
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaProcessor

## download_and_convert

```python
async def download_and_convert(self, url: str, output_format: str = "mp4", quality: str = "best") -> Dict[str, Any]:
    """
    Download video and optionally convert to different format.

Args:
    url: Video URL to download
    output_format: Desired output format
    quality: Quality preference
    
Returns:
    Dict containing processing results
    """
```
* **Async:** True
* **Method:** True
* **Class:** MediaProcessor

## get_capabilities

```python
def get_capabilities(self) -> Dict[str, Any]:
    """
    Get available capabilities and supported operations.

Returns:
    Dict containing capability information
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaProcessor
