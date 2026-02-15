# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/batch_processor/_batch_result.py'

Files last updated: 1752752076.2707334

Stub file last updated: 2025-07-17 04:40:25

## BatchResult

```python
@dataclass
class BatchResult:
    """
    Result of batch processing multiple files.

This class represents the result of processing a batch of files, including overall
statistics and individual file results.

Attributes:
    total_files (int): Total number of files in the batch.
    successful_files (int): Number of files processed successfully.
    failed_files (int): Number of files that failed processing.
    results (list[ProcessingResult]): list of individual file processing results.
    statistics (dict[str, Any]): Additional statistics about the batch processing.
    start_time (datetime): Time when the batch processing started.
    end_time (datetime): Time when the batch processing ended.

Methods:
    add_result(result): Add a processing result to the batch.
    mark_as_complete(): Mark the batch processing as complete.
    get_summary(): Get a summary dictionary of the batch processing.
    get_failed_files(): Get list of files that failed processing.
    get_successful_files(): Get list of successfully processed files.
    to_dict(): Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __post_init__

```python
def __post_init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** BatchResult

## __str__

```python
def __str__(self) -> str:
    """
    Get a string representation of the batch result.

Returns:
    A string representation of the batch result.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchResult

## add_result

```python
def add_result(self, result: ProcessingResult) -> None:
    """
    Add a file processing result to the batch.

Args:
    result: The file processing result to add.
    
Raises:
    ValueError: If result is None.
    AttributeError: If result is missing required attributes.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchResult

## get_failed_files

```python
def get_failed_files(self) -> list[str]:
    """
    Get a list of files that failed processing.

Returns:
    A list of paths to failed files.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchResult

## get_successful_files

```python
def get_successful_files(self) -> list[str]:
    """
    Get a list of files that were processed successfully.

Returns:
    A list of paths to successfully processed files.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchResult

## get_summary

```python
def get_summary(self) -> dict[str, Any]:
    """
    Get a summary of the batch processing.

Returns:
    A dictionary with summary information.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchResult

## mark_as_complete

```python
def mark_as_complete(self) -> None:
    """
    Mark the batch processing as complete.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchResult

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary representation of the batch result with keys:
    - total_files: Total number of files processed
    - successful_files: Number of successfully processed files
    - failed_files: Number of files that failed processing
    - results: List of individual ProcessingResult dictionaries
    - statistics: Additional batch processing statistics
    - start_time: ISO format timestamp when processing started
    - end_time: ISO format timestamp when processing ended (or None if in progress)
    """
```
* **Async:** False
* **Method:** True
* **Class:** BatchResult
