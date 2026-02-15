# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/monitors/security_monitor/_security_monitor.py'

Files last updated: 1751086524.5424216

Stub file last updated: 2025-07-17 05:28:52

## SecurityMonitor

```python
class SecurityMonitor:
    """
    Security manager for the Omni-Converter.

This class handles security validation.

Attributes:
    file_size_limits (dict[str, int]): Maximum file size limits by format (in bytes).
    allowed_formats (list[str]): list of allowed formats.
    security_rules (dict[str, Any]): Security rules for validation and sanitization.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
    """
    Initialize a security manager.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _check_archive_executables

```python
@staticmethod
def _check_archive_executables(file_path: str, format_name: str) -> list[str]:
    """
    Check for executable files in an archive.

Args:
    file_path: Path to the archive file.
    format_name: Format of the archive (zip, tar, etc.).
    
Returns:
    List of executable file paths found in the archive.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _check_archive_paths

```python
@staticmethod
def _check_archive_paths(file_path: str, format_name: str) -> list[str]:
    """
    Check for suspicious file paths in an archive.

Args:
    file_path: Path to the archive file.
    format_name: Format of the archive (zip, tar, etc.).
    
Returns:
    List of suspicious file paths found in the archive.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _check_archive_security

```python
def _check_archive_security(self, file_path: str, format_name: str, issues: list[str]) -> tuple[bool, str, list[str]]:
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _count_archive_files

```python
@staticmethod
def _count_archive_files(file_path: str, format_name: str) -> int:
    """
    Count the total number of files in an archive.

Args:
    file_path: Path to the archive file.
    format_name: Format of the archive (zip, tar, etc.).
    
Returns:
    Total number of files in the archive (excluding directories).
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _count_nested_archives

```python
@staticmethod
def _count_nested_archives(file_path: str, format_name: str) -> int:
    """
    Count the number of nested archive levels in an archive file.

Args:
    file_path: Path to the archive file.
    format_name: Format of the archive (zip, tar, etc.).
    
Returns:
    Number of nested archive levels found.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _count_nested_in_tar

```python
def _count_nested_in_tar(tar_path: str, current_depth: int = 0, max_depth: int = 10) -> int:
    """
    Recursively count nested archives in a TAR file.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _count_nested_in_zip

```python
def _count_nested_in_zip(zip_path: str, current_depth: int = 0, max_depth: int = 10) -> int:
    """
    Recursively count nested archives in a ZIP file.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _get_compression_ratio

```python
@staticmethod
def _get_compression_ratio(file_path: str, format_name: str) -> float:
    """
    Calculate the compression ratio of an archive file.

Args:
    file_path: Path to the archive file.
    format_name: Format of the archive (zip, tar, etc.).
    
Returns:
    Compression ratio (uncompressed_size / compressed_size).
    Returns 1.0 if unable to determine ratio.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _is_archive_encrypted

```python
@staticmethod
def _is_archive_encrypted(file_path: str, format_name: str) -> bool:
    """
    Check if an archive is encrypted or password protected.

Args:
    file_path: Path to the archive file.
    format_name: Format of the archive (zip, tar, etc.).
    
Returns:
    True if the archive is encrypted, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _is_archive_file

```python
def _is_archive_file(filename: str) -> bool:
    """
    Check if a filename appears to be an archive.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _is_executable

```python
def _is_executable(self, file_path: str) -> bool:
    """
    Check if a file is executable.

Args:
    file_path: The path to the file.
    
Returns:
    True if the file is executable, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## _is_suspicious_path

```python
@staticmethod
def _is_suspicious_path(path: str) -> bool:
    """
    Check if a file path is suspicious.

Args:
    path: The file path to check.
    
Returns:
    True if the path is suspicious, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## is_file_safe

```python
def is_file_safe(self, file_path: str, format_name: Optional[str] = None) -> bool:
    """
    Check if a file is safe.

Args:
    file_path: The path to the file.
    format_name: The format of the file, if known.
    
Returns:
    True if the file is safe, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## set_allowed_formats

```python
def set_allowed_formats(self, formats: list[str]) -> None:
    """
    Set the list of allowed formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## set_file_size_limits

```python
def set_file_size_limits(self, limits: dict[str, int]) -> None:
    """
    Set file size limits.

Args:
    limits: Dictionary of file size limits by format (in bytes).
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## set_security_rules

```python
def set_security_rules(self, rules: dict[str, Any]) -> None:
    """
    Set the dictionary of security rules.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor

## validate_security

```python
def validate_security(self, file_path: str, format_name: Optional[str] = None) -> "SecurityResult":
    """
    Validate the security of a file.

Args:
    file_path: The path to the file.
    format_name: The format of the file, if known.
    
Returns:
    A SecurityResult object with the validation results.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SecurityMonitor
