# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/file_validator/_file_validator.py'

## FileValidator

```python
class FileValidator:
    """
    File validator for the Omni-Converter.

Validates files for processing, checking for issues like:
- File exists and is readable
- File size is within limits
- File format is supported
- File is not corrupted
    """
```
## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None):
    """
    Initialize the basic validator.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileValidator

## _check_for_null_bytes_and_permissions

```python
@staticmethod
def _check_for_null_bytes_and_permissions(file_path: str, format_name: str, result: list[str]) -> bool:
    """
    Check for null bytes and permission issues that could cause hangs

Args:
    file_path: The path to the file.
    format_name: The format of the file
    
Returns:
    True if the file is corrupt, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileValidator

## get_validation_errors

```python
def get_validation_errors(self, file_path: str, format_name: Optional[str] = None) -> list[str]:
    """
    Get validation errors for a file.

Args:
    file_path: The path to the file.
    format_name: The format of the file, if known. Will be detected if not provided.
    
Returns:
    A list of validation errors.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileValidator

## is_valid_for_processing

```python
def is_valid_for_processing(self, file_path: str, format_name: Optional[str] = None) -> bool:
    """
    Check if a file is valid for processing.

Args:
    file_path: The path to the file.
    format_name: The format of the file, if known. Will be detected if not provided.
    
Returns:
    True if the file is valid for processing, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileValidator

## validate_file

```python
def validate_file(self, file_path: str, format_name: Optional[str] = None) -> ValidationResult:
    """
    Validate a file for processing.

Args:
    file_path: The path to the file.
    format_name: The format of the file, if known. Will be detected if not provided.
    
Returns:
    A validation result.
    
Raises:
    FileNotFoundError: If the file does not exist.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileValidator
