# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/interfaces/_cli.py'

Files last updated: 1751075895.078516

Stub file last updated: 2025-07-17 04:44:10

## CLI

```python
class CLI:
    """
    Command Line Interface for the Omni-Converter.

Attributes:
    resources (dict[str, Callable]): Dictionary of callable functions and classes.
    configs (Configs): A pydantic mode of settings to use across the program.

Private Attributes:
    _batch_processor (BatchProcessor): Handles batch processing of files.
    _progress_callback (ProgressCallback): Callback for progress updates.
    _processing_pipeline (ProcessingPipeline): Pipeline for processing files.
    _list_normalizers (Callable): Function to list available text normalizers.
    _list_output_formats (Callable): Function to list available output formats.
    _list_supported_formats (Callable): Function to list supported input formats.
    _show_version (Callable): Function to display version information.
    _logger (Logger): Logger instance for logging messages.
    _tqdm (Dependency): Dependency for progress bar functionality.
    _resource_monitor (ResourceMonitor): Monitors system resources during processing.
    _error_monitor (ErrorMonitor): Monitors errors during processing.
    _security_monitor (SecurityMonitor): Monitors security issues during processing.

Methods:
    make_parser_from_options_basemodel() -> argparse.Namespace:
        Parses command line arguments and returns them as a Namespace object.
    process_file(input_path: str, output_path: Optional[str] = None,
                 output_dir: Optional[str] = None, format: str = "txt",
                 include_metadata: bool = True, extract_metadata: bool = True,
                 normalize_text: bool = True, quality_threshold: float = 0.9,
                 continue_on_error: bool = True, max_batch_size: int = 100,
                 parallel: bool = False, max_threads: int = 4,
                 sanitize: bool = True, max_cpu: int = 80,
                 max_memory: int = 6144, show_progress: bool = False,
                 options: Optional[dict[str, Any]] = None) -> bool:
        Processes a single file and converts it to the specified format.
        Returns True if successful, False otherwise.
    process_directory(dir_path: str, output_dir: Optional[str] = None,
                      options: Optional[dict[str, Any]] = None,
                      show_progress: bool = True, recursive: bool = False) -> BatchResult:
        Processes all files in a directory and returns a BatchResult object with processing results.
    main() -> int:
        Main entry point for the CLI. Parses arguments and processes input files or directories.
        Returns an exit code: 0 for success, 1 for failure.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None):
    """
    Initialize the argparse CLI.

Args:
    resources: Dictionary of resource providers for interfaces
    configs: Configuration settings to use across interfaces.
        If None, default configs will be used.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CLI

## _callback

```python
def _callback(current, total, current_file):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## main

```python
def main(self) -> int:
    """
    Main entry point.

Returns:
    Exit code. 0 for success, 1 for failure.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CLI

## make_parser_from_options_basemodel

```python
def make_parser_from_options_basemodel(self) -> argparse.Namespace:
    """
    Parse command line arguments.

Returns:
    argparse.Namespace: The parsed arguments.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CLI

## process_directory

```python
def process_directory(self, dir_path: str, output_dir: Optional[str] = None, options: Optional[BaseModel | dict[str, Any]] = None, show_progress: bool = True, recursive: bool = False) -> "BatchResult":
    """
    Process all files in a directory.

Args:
    dir_path: The path to the directory to process.
    output_dir: The directory to write output files to. If None, prints content to stdout.
    options: Processing options. If None, default options are used.
    show_progress: Whether to show a progress bar.
    recursive: Whether to process directories recursively.
    
Returns:
    BatchResult object with processing results.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CLI

## process_file

```python
def process_file(self, input_path: str, output_path: Optional[str] = None, output_dir: Optional[str] = None, format: str = "txt", include_metadata: bool = True, extract_metadata: bool = True, normalize_text: bool = True, quality_threshold: float = 0.9, continue_on_error: bool = True, max_batch_size: int = 100, parallel: bool = False, max_threads: int = 4, sanitize: bool = True, max_cpu: int = 80, max_memory: int = 6144, show_progress: bool = False, options: Optional[BaseModel | dict[str, Any]] = None) -> bool:
    """
    Process a single file.

Args:
    input_path: The path to the input file.
    options: A pydantic model of optional processing options. If None, default options are used.
    Currently supported options:


    output_path: The path to the output file. If None, print to stdout.
    output_dir: The directory to write output files to. If None, prints content to stdout.
    format: The output format (e.g., "txt", "json", "md"). Default is "txt".
    include_metadata: Whether to include metadata in the output. Default is True.
    extract_metadata: Whether to extract metadata from the input file. Default is True.
    normalize_text: Whether to normalize the text during processing. Default is True.
    quality_threshold: The quality threshold for processing (0.0 to 1.0). Default is 0.9.
    continue_on_error: Whether to continue processing if an error occurs. Default is True.
    max_batch_size: The maximum number of files to process in a batch. Default is 100.
    parallel: Whether to enable parallel processing. Default is False.
    max_threads: The maximum number of worker threads for parallel processing. Default is 4.
    sanitize: Whether to sanitize the content during processing. Default is True.
    max_cpu: The maximum CPU usage percentage (0-100). Default is 80.
    max_memory: The maximum memory usage in MB. Default is 6144 (6GB).
    show_progress: Whether to show a progress bar during processing. Default is False.
    options: Additional processing options. If None, default options are used.

Returns:
    True if successful, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** CLI
