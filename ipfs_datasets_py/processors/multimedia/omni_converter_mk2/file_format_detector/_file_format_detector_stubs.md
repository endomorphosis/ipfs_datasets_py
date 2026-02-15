# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/file_format_detector/_file_format_detector.py'

Files last updated: 1751233062.0888102

Stub file last updated: 2025-07-17 04:43:35

## FileFormatDetector

```python
class FileFormatDetector:
    """
    Format detector for the Omni-Converter.

Detects the format of files based on their content and extension using injected dependencies.
If a format is not supported, it returns None.

Attributes:
    _get_file_info: Callable for getting file information
    _format_registry: dict mapping categories to supported formats
    _format_signatures: dict mapping MIME types to format names
    _format_extensions: dict mapping file extensions to format names
    _logger: Logger instance for debug/warning messages
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Any], configs: Configs) -> None:
    """
    Initialize the format detector with injected dependencies.

Args:
    resources: Dictionary containing required callables and data:
        - 'get_file_info': Function to get file information
        - 'format_registry': dict of supported formats by category
            Example:
                {
                    'images': ['jpeg', 'png', 'gif', 'webp'],
                    'documents': ['pdf', 'docx', 'txt', 'md'],
                    'audio': ['mp3', 'wav', 'flac'],
                    'video': ['mp4', 'avi', 'mkv']
                }
        - 'format_signatures': dict mapping MIME types to formats
            Example:
                {
                    'image/jpeg': 'jpeg',
                    'image/png': 'png',
                    'application/pdf': 'pdf',
                    'text/plain': 'txt',
                    'audio/mpeg': 'mp3'
                }
        - 'format_extensions': dict mapping extensions to formats
            Example:
                {
                    '.jpg': 'jpeg',
                    '.jpeg': 'jpeg', 
                    '.png': 'png',
                    '.pdf': 'pdf',
                    '.txt': 'txt',
                    '.mp3': 'mp3'
                }
        - 'logger': Logger instance
    configs: Pydantic configuration model
    
Raises:
    KeyError: If required resources are missing
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileFormatDetector

## _concatenate_frozensets_into_list

```python
@staticmethod
def _concatenate_frozensets_into_list(formats: list[frozenset[str]]) -> set[str]:
    """
    Convert a list of frozensets into a single set.

Args:
    list_of_frozen_sets: List of frozensets to convert.
    
Returns:
    A single set containing all elements from the frozensets.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileFormatDetector

## _get_format_signatures

```python
def _get_format_signatures(self, file_info, file_path) -> Optional[dict[str, str]]:
```
* **Async:** False
* **Method:** True
* **Class:** FileFormatDetector

## detect_format

```python
def detect_format(self, file_path: str) -> tuple[Optional[str], Optional[str]]:
    """
    Detect the format of a file using injected dependencies.

Args:
    file_path: The path to the file.
    
Returns:
    A tuple of (format, category) if the format is detected, (None, None) otherwise.
        - format: The detected format name (e.g., 'jpeg', 'pdf').
        - category: The category of the format (e.g., 'images', 'documents').
    
Raises:
    FileNotFoundError: If the file does not exist.
    PermissionError: If the file cannot be read.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileFormatDetector

## get_format_category

```python
def get_format_category(self, format_name: str) -> Optional[str]:
    """
    Get the category for a format

Args:
    format_name: The format name.
    
Returns:
    str | None: The category if found, None otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileFormatDetector

## is_format_supported

```python
def is_format_supported(self, format_name: str) -> bool:
    """
    Check if a format is supported.

Args:
    format_name: The format name.
    
Returns:
    True if the format is supported, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileFormatDetector

## supported_formats

```python
@property
def supported_formats(self) -> dict[str, set[str]]:
    """
    Get the supported formats from injected registry.

Returns:
    A dictionary of sets, where each key is the category, and every.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileFormatDetector
