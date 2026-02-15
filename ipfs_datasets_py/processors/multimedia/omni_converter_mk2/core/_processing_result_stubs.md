# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/_processing_result.py'

Files last updated: 1751085490.4477873

Stub file last updated: 2025-07-17 05:39:35

## ProcessingResult

```python
@dataclass
class ProcessingResult:
    """
    Result of processing a file.

This class represents the result of processing a file, including success status,
file paths, errors, and metadata.

Attributes:
    success (bool): Whether the processing was successful.
    file_path (str): The path to the input file.
    output_path (str): The path to the output file.
    format (str): The detected format of the input file.
    errors (list[str]): list of errors encountered during processing.
    metadata (dict[str, Any]): Metadata about the processing.
    content_hash (str): Hash of the content for verification.
    timestamp (datetime): Time when the processing was completed.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __str__

```python
def __str__(self) -> str:
    """
    Get a string representation of the result.

Returns:
    A string representation of the processing result.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingResult

## add_error

```python
def add_error(self, error: str) -> None:
    """
    Add an error to the result.

Args:
    error: The error message to add.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingResult

## add_metadata

```python
def add_metadata(self, key: str, value: Any) -> None:
    """
    Add metadata to the result.

Args:
    key: The metadata key.
    value: The metadata value.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingResult

## error_string

```python
@property
def error_string(self) -> str:
    """
    Get the errors as a formatted string.

Returns:
    A formatted string of errors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingResult

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary representation of the processing result.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessingResult
