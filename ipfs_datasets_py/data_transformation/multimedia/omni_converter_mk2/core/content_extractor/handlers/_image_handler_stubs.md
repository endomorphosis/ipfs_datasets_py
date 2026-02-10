# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/handlers/_image_handler.py'

Files last updated: 1750023782.1233895

Stub file last updated: 2025-07-17 05:44:44

## ImageHandler

```python
class ImageHandler:
    """
    Framework class for handling image-based formats using IoC pattern.

This class only contains orchestration logic and delegates all format-specific
processing to injected processors via the resources dictionary.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable], configs: Configs):
    """
    Initialize the image handler with injected dependencies.

Args:
    resources: Dictionary of callable resources including processors and utilities.
    configs: Configuration settings.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageHandler

## can_handle

```python
def can_handle(self, file_path: str, format_name: Optional[str] = None) -> bool:
    """
    Check if this handler can process the given file format.

Args:
    file_path: Path to the file.
    format_name: Format of the file, if known.
    
Returns:
    True if this handler can process the format, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageHandler

## capabilities

```python
@property
def capabilities(self) -> dict[str, Any]:
```
* **Async:** False
* **Method:** True
* **Class:** ImageHandler

## extract_content

```python
def extract_content(self, file_path: str, format_name: str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]] | None:
    """
    Extract content from an image file using the appropriate processor.

Args:
    file_path: Path to the file.
    format_name: Format of the file.
    options: Processing options.
    
Returns:
    Tuple of (text content, metadata, sections).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageHandler
