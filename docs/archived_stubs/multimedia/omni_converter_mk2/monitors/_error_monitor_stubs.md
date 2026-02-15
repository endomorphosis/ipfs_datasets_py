# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/monitors/_error_monitor.py'

Files last updated: 1751073793.5335886

Stub file last updated: 2025-07-17 05:28:21

## ErrorMonitor

```python
class ErrorMonitor:
    """
    Error handler for the Omni-Converter.

This class centralizes error handling and reporting, providing consistent
error management across the application.

Attributes:
    logger: The logger to use for error logging.
    error_counters (dict[str, int]): Counters for different error types.
    error_types (set[str]): set of known error types.
    suppress_errors (bool): Whether to suppress errors.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
    """
    Initialize an error handler.

Args:
    resource: A dictionary of callables, including:
        - logger: A logger instance for logging errors.
    configs: Configuration object containing settings for error handling, including:
        - processing.suppress_errors: Whether to suppress errors (default: False).
        - paths.ROOT_DIR: The program's root directory.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## core_dump

```python
def core_dump(self) -> None:
    """
    Writes the error monitor's current state to a file to the logs directory.

The file contains:
- The total number of errors recorded.
- A list of all error types encountered.
- A detailed breakdown of error counts by type.

If the error count is zero (i.e. no errors detected) when the function is run, no log will be created.

Raises:
    Exception: If an unexpected error occurs while attempting to write to the log file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## error_statistics

```python
@property
def error_statistics(self) -> dict[str, Any]:
    """
    Get error statistics.

Returns:
    A dictionary of error statistics.
    - total_errors: Total number of errors handled.
    - error_types: List of unique error types encountered.
    - error_counts: Dictionary of error types and their counts.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## get_error_count

```python
def get_error_count(self, error_type: Optional[Type[Exception] | str] = None) -> int:
    """
    Get the count of a specific error type or total errors.

Args:
    error_type (str|Exception|None): The error type to get the count for. If None, total errors are returned.

Returns:
    The count of the specified error type or total errors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## get_most_common_errors

```python
def get_most_common_errors(self, limit: int = 5) -> list[dict[str, Any]]:
    """
    Get the most common errors.

Args:
    limit: Maximum number of errors to return.

Returns:
    A list of dictionaries with error type and count.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## handle_error

```python
def handle_error(self, error: Exception | str, context: Optional[dict[str, Any]] = {}) -> None:
    """
    Handle an error.

Args:
    error: The error to handle.
    context: Additional context for the error.

Returns:
    None

Raises:
    Exception: If suppress_errors is False and error is an exception.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## has_errors

```python
@property
def has_errors(self) -> bool:
    """
    Check if any errors have been handled.

Returns:
    True if errors have been handled, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## log_error

```python
def log_error(self, error: Exception | str, context: Optional[dict[str, Any]] = {}) -> None:
    """
    Log an error that occurred when running the pipeline.

Args:
    error: The error to log.
    context: Additional context for the error.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## logger

```python
@property
def logger(self) -> Logger:
    """
    Get the logger for this error handler.

Returns:
    The logger instance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## reset_error_counters

```python
def reset_error_counters(self) -> None:
    """
    Reset error counters.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor

## set_error_suppression

```python
def set_error_suppression(self, suppress: bool) -> None:
    """
    Set error suppression.

Args:
    suppress: Whether to suppress errors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ErrorMonitor
