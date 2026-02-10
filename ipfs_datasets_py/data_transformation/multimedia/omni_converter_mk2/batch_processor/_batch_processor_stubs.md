# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/batch_processor/_batch_processor.py'

Files last updated: 1751233802.519849

Stub file last updated: 2025-07-17 04:40:25

## BatchProcessor

```python
class BatchProcessor:
    """
    Batch processor for the Omni-Converter.

This class orchestrates the processing of multiple files in batches, handling
resource management, error handling, and security validation.

Attributes:
    pipeline: The processing pipeline to use.
    error_monitor: The error handler to use.
    resource_monitor: The resource monitor to use.
    security_monitor: The security manager to use.
    max_batch_size (int): Maximum number of files to process in a single batch.
    continue_on_error (bool): Whether to continue processing if errors occur.
    max_threads (int): Maximum number of worker threads for parallel processing.
    cancellation_requested (bool): Whether processing cancellation has been requested.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Counter

```python
class Counter(object):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _BatchState

```python
class _BatchState(StrEnum):
    """
    Enum for batch processing states.

Attributes:
    IDLE: No processing is currently happening.
    PROCESSING: Files are being processed.
    CANCELLING: Processing is being cancelled.
    COMPLETED: Processing has completed.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, manager, init_val: int = 0) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** Counter

## __init__

```python
def __init__(self, configs: Configs = None, resources: dict[str, Callable] = None):
    """
    Initialize a batch processor.

Args:
    configs: Configuration object containing processing settings.
    resources: Dictionary of resource objects and functions.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _assert_positive_int

```python
@staticmethod
def _assert_positive_int(var: Any, name: str) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _process_chunk

```python
def _process_chunk(self, file_paths: list[str], output_dir: Optional[str], options: Optional[dict[str, Any]], progress_callback: Optional[Callable], total_count: int, current_index: int) -> list['ProcessingResult']:
    """
    Process a chunk of files.

Args:
    file_paths: list of file paths to process.
    output_dir: Directory to write output files to.
    options: Processing options.
    progress_callback: Progress callback function.
    total_count: Total number of files in the full batch.
    current_index: Current index in the full batch.
    
Returns:
    List of ProcessingResult objects for the processed files.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _process_files_parallel

```python
def _process_files_parallel(self, file_paths: list[str], output_dir: Optional[str], options: dict[str, Any], progress_callback: Optional[Callable], total_count: int, current_index: int) -> list['ProcessingResult']:
    """
    Process files in parallel using a thread pool.

Args:
    file_paths: list of file paths to process.
    output_dir: Directory to write output files to.
    options: Processing options.
    progress_callback: Progress callback function.
    total_count: Total number of files in the full batch.
    current_index: Current index in the full batch.
    
Returns:
    List of ProcessingResult objects for the processed files.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _process_files_sequential

```python
def _process_files_sequential(self, file_paths: list[str], output_dir: Optional[str], options: dict[str, Any], progress_callback: Optional[Callable], total_count: int, current_index: int) -> list[ProcessingResult]:
    """
    Process files sequentially.

Args:
    file_paths: list of file paths to process.
    output_dir: Directory to write output files to.
    options: Processing options.
    progress_callback: Progress callback function.
    total_count: Total number of files in the full batch.
    current_index: Current index in the full batch.
    
Returns:
    List of ProcessingResult objects for the processed files.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _process_single_file

```python
def _process_single_file(self, file_path: str, output_path: Optional[str], options: dict[str, Any]) -> ProcessingResult:
    """
    Process a single file.

Args:
    file_path: Path to the file to process.
    output_path: Path to write output to.
    options: Processing options.
    
Returns:
    ProcessingResult object for the processed file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _safe_progress_callback

```python
def _safe_progress_callback(self, progress_callback: Optional[Callable], current: int, total: int, filename: str) -> None:
    """
    Safely call progress callback with exception handling.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## _safe_resource_check

```python
def _safe_resource_check(self) -> tuple[bool, str]:
    """
    Safely check resource availability with exception handling.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## cancel_processing

```python
def cancel_processing(self) -> None:
    """
    Cancel ongoing batch processing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## eta

```python
@property
def eta(self) -> Optional[float]:
    """
    Calculate estimated time remaining for current batch.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## increment

```python
def increment(self):
```
* **Async:** False
* **Method:** True
* **Class:** Counter

## ongoing_batch_result

```python
@property
def ongoing_batch_result(self):
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## process_batch

```python
def process_batch(self, file_paths: list[str] | str, output_dir: Optional[str] = None, options: Optional[dict[str, Any]] = None, progress_callback: Optional[Callable] = None) -> BatchResult:
    """
    Process a batch of files.

Args:
    file_paths: list of file paths to process, or a directory path to
        recursively process all files within.
    output_dir: Directory to write output files to. If None, files will
        be processed but output will not be written to disk.
    options: Processing options to pass to the pipeline.
    progress_callback: Optional callback function for reporting progress.
        The function should accept current_count, total_count, and current_file.
        
Returns:
    A BatchResult object with the results of the batch processing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## processing_status

```python
@property
def processing_status(self) -> dict[str, Any]:
    """
    Get the current status of batch processing.

Returns:
    A dictionary with the current status including both legacy and new format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## set_continue_on_error

```python
def set_continue_on_error(self, flag: bool) -> None:
    """
    Set whether to continue processing if errors occur.

Args:
    flag: Whether to continue processing if errors occur.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## set_max_batch_size

```python
def set_max_batch_size(self, size: int) -> None:
    """
    Set the maximum batch size.

Args:
    size: Maximum number of files to process in a single batch.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## set_max_threads

```python
def set_max_threads(self, count: int) -> None:
    """
    Set the maximum number of worker threads for parallel processing.

Args:
    count: Maximum number of worker threads.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchProcessor

## value

```python
def value(self):
```
* **Async:** False
* **Method:** True
* **Class:** Counter
