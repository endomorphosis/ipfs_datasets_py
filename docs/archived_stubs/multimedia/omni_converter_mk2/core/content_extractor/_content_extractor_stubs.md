# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/_content_extractor.py'

Files last updated: 1752613712.9993467

Stub file last updated: 2025-07-17 05:42:08

## ContentExtractor

```python
class ContentExtractor:
    """
    Framework for extracting content from files.
This class provides the logic for orchestrating format handlers

Base implementation of a format handler without inheritance.

Provides common functionality for format handlers.

Attributes:
    resources (dict): Dictionary of resources and dependencies.
    configs (Configs): Configuration settings.
    format_processors (dict): Processors for different formats.
    supported_formats (set): Set of formats supported by this handler.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
    """
    Initialize the content extractor.

Args:
    resources: Dictionary of callables and services used by the extractor.
    configs: Pydantic BaseModel containing configuration settings. Settings are accessed via attributes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentExtractor

## _extract

```python
def _extract(self, file_path: str, options: dict[str, Any]) -> Content:
    """
    Perform the actual extraction of content from a file.

Args:
    file_path: The path to the file.
    options: Extraction options. These include:
        - format: The format of the file (if not provided, it will be detected).
        - other options specific to the processor.
    
Returns:
    The extracted content.
    
Raises:
    Exception: If an error occurs during extraction.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentExtractor

## _validate_input

```python
def _validate_input(self, file_path: str, format_name: str, handler_name: str, format_set: set) -> bool:
    """
    Validate that the file can be processed by this handler.

Args:
    file_path: The path to the file.
    
Returns:
    True if the file is valid for this handler, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentExtractor

## can_handle

```python
def can_handle(self, file_path: str, format_name: Optional[str] = None) -> bool:
    """
    Check if extractor can process the given file.

Args:
    file_path: The path to the file.
    format_name: The format of the file, if known.
    
Returns:
    True if this handler can process the file, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentExtractor

## capabilities

```python
@property
def capabilities(self) -> dict[str, Any]:
    """
    Get the capabilities of the available handlers.

Returns:
    A dictionary of capabilities, such as supported formats and extraction options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentExtractor

## extract_content

```python
def extract_content(self, file_path: str, format_name: str, options: Optional[dict[str, Any]] = None) -> Content:
    """
    Extract content from a file.

Args:
    file_path: The path to the file.
    options: Optional extraction options.
    
Returns:
    The extracted content.
    
Raises:
    FileNotFoundError: If the file does not exist.
    PermissionError: If the file cannot be read.
    ValueError: If the file is not valid for this handler.
    Exception: If an error occurs during extraction.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ContentExtractor
