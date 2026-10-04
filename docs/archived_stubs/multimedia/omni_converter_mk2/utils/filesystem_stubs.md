# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/filesystem.py'

Files last updated: 1750808710.8958905

Stub file last updated: 2025-07-17 05:29:23

## FileContent

```python
class FileContent:
    """
    Content of a file.

Attributes:
    raw_content (bytes): The raw binary content of the file.
    text_content (str): The text content of the file, if applicable.
    encoding (str): The encoding of the text content.
    size (int): The size of the content in bytes.
    mime_type (str): The MIME type of the content.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FileInfo

```python
class FileInfo(BaseModel):
    """
    Information about a file.

Attributes:
    path (str): The path to the file.
    size (int): The size of the file in bytes.
    modified_time (datetime): The time the file was last modified.
    mime_type (str): The MIME type of the file.
    extension (str): The file extension.
    is_readable (bool): Whether the file is readable.
    is_writable (bool): Whether the file is writable.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FileSystem

```python
class FileSystem:
    """
    File system utility functions.

Provides functions for file reading, writing, and information retrieval.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, raw_content: bytes, encoding: str = "utf-8", mime_type: Optional[str] = None):
    """
    Initialize file content.

Args:
    raw_content: The raw binary content of the file.
    encoding: The encoding to use for text conversion.
    mime_type: The MIME type of the content. If None, will be guessed from content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileContent

## _determine_mime_type

```python
def _determine_mime_type(path_or_bytes: str | bytes | None) -> Optional[str]:
    """
    Determine the MIME type of a file.

Args:
    file_path: The path to the file.
    
Returns:
    The MIME type of the file.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## as_binary

```python
@property
def as_binary(self) -> bytes:
    """
    Get the content as binary.

Returns:
    The raw binary content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileContent

## create_directory

```python
@staticmethod
def create_directory(directory_path: str) -> bool:
    """
    Create a directory.

Args:
    directory_path: The path to the directory.
    
Returns:
    True if the directory was created successfully, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileSystem

## file_exists

```python
@staticmethod
def file_exists(file_path: str) -> bool:
    """
    Check if a file exists.

Args:
    file_path: The path to the file.
    
Returns:
    True if the file exists, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileSystem

## from_path

```python
@classmethod
def from_path(cls, path: str) -> "FileInfo":
    """
    Create FileInfo from a file path.

Args:
    path: The path to the file.
    
Returns:
    FileInfo instance with populated data.
    
Raises:
    FileNotFoundError: If the file does not exist.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileInfo

## get_as_text

```python
def get_as_text(self, encoding: Optional[str] = None) -> str:
    """
    Get the content as text.

Args:
    encoding: The encoding to use. If None, uses the current encoding.
    
Returns:
    The content as text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileContent

## get_file_info

```python
@staticmethod
def get_file_info(path: str) -> FileInfo:
    """
    Get information about a file.

Args:
    file_path: The path to the file.
    
Returns:
    File information.
    
Raises:
    FileNotFoundError: If the file does not exist.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileSystem

## list_files

```python
@staticmethod
def list_files(directory: str, pattern: str = "*.*") -> list[str]:
    """
    list files in a directory.

Args:
    directory: The directory to list files in.
    pattern: The pattern to match files against.
    
Returns:
    A list of file paths matching the pattern.
    
Raises:
    FileNotFoundError: If the directory does not exist.
    PermissionError: If the directory cannot be read.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileSystem

## read_file

```python
@staticmethod
def read_file(file_path: str, mode: str = "rb") -> FileContent:
    """
    Read a file.

Args:
    file_path: The path to the file.
    mode: The mode to open the file in. Default is binary mode.
    
Returns:
    The file content.
    
Raises:
    FileNotFoundError: If the file does not exist.
    PermissionError: If the file cannot be read.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileSystem

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary containing the file information.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileInfo

## write_file

```python
@staticmethod
def write_file(file_path: str, content: str | bytes, mode: str = "wb") -> bool:
    """
    Write to a file.

Args:
    file_path: The path to the file.
    content: The content to write.
    mode: The mode to open the file in. Default is binary mode.
    
Returns:
    True if the file was written successfully, False otherwise.
    
Raises:
    PermissionError: If the file cannot be written.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FileSystem
