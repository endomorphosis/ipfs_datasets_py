# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/multimedia/media_utils.py'

Files last updated: 1751408933.7764564

Stub file last updated: 2025-07-07 02:00:56

## MediaUtils

```python
class MediaUtils:
    """
    Utility functions for multimedia operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_duration

```python
@classmethod
def format_duration(cls, seconds: float) -> str:
    """
    Format duration in human-readable format.

Args:
    seconds: Duration in seconds
    
Returns:
    Formatted duration string (HH:MM:SS)
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaUtils

## format_file_size

```python
@classmethod
def format_file_size(cls, size_bytes: int) -> str:
    """
    Format file size in human-readable format.

Args:
    size_bytes: Size in bytes
    
Returns:
    Formatted size string
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaUtils

## get_file_type

```python
@classmethod
def get_file_type(cls, file_path: Union[str, Path]) -> Optional[str]:
    """
    Determine the type of media file.

Args:
    file_path: Path to the media file
    
Returns:
    Media type ('video', 'audio', 'image') or None
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaUtils

## get_mime_type

```python
@classmethod
def get_mime_type(cls, file_path: Union[str, Path]) -> Optional[str]:
    """
    Get MIME type for a media file.

Args:
    file_path: Path to the media file
    
Returns:
    MIME type string or None
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaUtils

## get_supported_formats

```python
@classmethod
def get_supported_formats(cls) -> Dict[str, Set[str]]:
    """
    Get all supported media formats by type.

Returns:
    Dict mapping media types to supported formats
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaUtils

## is_media_file

```python
@classmethod
def is_media_file(cls, file_path: Union[str, Path]) -> bool:
    """
    Check if file is a supported media file.

Args:
    file_path: Path to check
    
Returns:
    True if file is a supported media type
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaUtils

## sanitize_filename

```python
@classmethod
def sanitize_filename(cls, filename: str) -> str:
    """
    Sanitize filename for safe file system usage.

Args:
    filename: Original filename
    
Returns:
    Sanitized filename
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaUtils

## validate_url

```python
@classmethod
def validate_url(cls, url: str) -> bool:
    """
    Basic URL validation for media sources.

Args:
    url: URL to validate
    
Returns:
    True if URL appears valid
    """
```
* **Async:** False
* **Method:** True
* **Class:** MediaUtils
