# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/interfaces/_python_api.py'

Files last updated: 1751075895.078516

Stub file last updated: 2025-07-17 04:44:10

## PythonAPI

```python
class PythonAPI:
    """
    Python API for the Omni-Converter.

This class provides methods for programmatically using the Omni-Converter functionality,
including single file conversion, batch processing, and configuration management.

Attributes:
    configs: The configuration manager to use.
    batch_processor: The batch processor to use.
    resource_monitor: The resource monitor to use.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None):
    """
    Initialize the Python API.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonAPI

## _get_default_options

```python
def _get_default_options(self) -> dict[str, Any]:
    """
    Get default options from configuration.

Returns:
    Default options as a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonAPI

## convert_batch

```python
def convert_batch(self, file_paths: list[str] | str, output_dir: Optional[str] = None, format: str = "txt", include_metadata: bool = True, extract_metadata: bool = True, normalize_text: bool = True, quality_threshold: float = 0.9, continue_on_error: bool = True, max_batch_size: int = 100, parallel: bool = False, max_threads: int = 4, sanitize: bool = True, max_cpu: int = 80, max_memory: int = 6144, show_progress: bool = False) -> BatchResult:
    """
    Convert multiple files to text.

Args:
    file_paths: list of file paths to convert, or a directory to recursively process.
    output_dir: Directory to write output files to. 
        If None, text is still extracted but not written to files.
    options: Conversion options. If None, default options are used.
    show_progress: Whether to show a progress bar (if in interactive environment). # TODO Implement.
    
Returns:
    A BatchResult object with the results of the batch conversion.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonAPI

## convert_file

```python
def convert_file(self, file_path: str, output_dir: Optional[str] = None, format: str = "txt", include_metadata: bool = True, extract_metadata: bool = True, normalize_text: bool = True, quality_threshold: float = 0.9, continue_on_error: bool = True, max_batch_size: int = 100, parallel: bool = False, max_threads: int = 4, sanitize: bool = True, max_cpu: int = 80, max_memory: int = 6144, show_progress: bool = False, output_path: Optional[str] = None) -> ProcessingResult:
    """
    Convert a single file to text.

Args:
    - file_path: The path to the file to convert.
    - output_path: Optional path to write the output to.
    - output_dir: Optional[str] - Directory to write output files to.
    - format: str - Output format for the converted text (default: "txt").
    - include_metadata: bool - Whether to include file metadata in the output (default: True).
    - extract_metadata: bool - Whether to extract metadata from the data in the input files (default: True).
    - normalize_text: bool - Whether to normalize text (e.g., remove extra whitespace, convert to lowercase, etc.) (default: True).
    - quality_threshold: float - Arbitrary threshold for quality filtering (default: 0.9).
    - continue_on_error: bool - Whether to continue processing files even if some fail (default: True).
    - max_batch_size: int - Maximum number of files to process in a single batch (default: 100).
    - parallel: bool - Whether to process files in parallel (default: False).
    - max_threads: int - Maximum number of worker threads to use for parallel processing (default: 4).
    - sanitize: bool - Whether to sanitize output files (e.g. remove executable code, etc.) (default: True).
    - max_cpu: int - Maximum CPU usage percentage allowed (default: 80).
    - max_memory: int - Maximum memory usage in MB (default: 6144 i.e. 6GB).
    - show_progress: bool - Whether to show a progress bar (default: False, TODO: Unused argument. Implement).
Returns:
    A ProcessingResult object with the result of the conversion.
    
Raises:
    FileNotFoundError: If the file does not exist.
    ValueError: If the file is not valid for conversion.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonAPI

## get_config

```python
def get_config(self) -> dict[str, Any]:
    """
    Get the current configuration.

Returns:
    The current configuration as a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonAPI

## set_config

```python
def set_config(self, config_dict: dict[str, Any]) -> bool:
    """
    Set multiple configuration values at once.

Args:
    config_dict: A dictionary of configuration values to set.
        Keys can use dot notation for nested settings.
        
Returns:
    True if the configuration was successfully set, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonAPI

## supported_formats

```python
@cached_property
def supported_formats(self) -> dict[str, list[str]]:
    """
    Get all supported formats, organized by category.

Returns:
    A dictionary mapping format categories to lists of supported formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PythonAPI
