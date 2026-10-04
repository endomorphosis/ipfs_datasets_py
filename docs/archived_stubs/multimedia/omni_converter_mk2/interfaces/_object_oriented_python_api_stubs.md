# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/interfaces/_object_oriented_python_api.py'

Files last updated: 1750718855.7290506

Stub file last updated: 2025-07-17 04:44:10

## Convert

```python
class Convert(PythonAPI):
    """
    Public class for object-oriented access to the Omni-Converter.
Similar to Pathlib's Path class, this class provides extensions to the API to make it
certain operations more idiomatic and efficient.

Methods:
    - walk_and_convert: Walk through a directory and convert all files.
    - estimate_file_count: Estimate the number of files in a directory that can potentially be converted.
    - convert: Convert a file or directory to text.
    - 
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, *paths):
    """
    Initialize the Convert class.

Args:
    *paths: Variable number of file or directory paths to convert.
           If empty, the converter starts in "receiver" mode for >> operator.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## __new__

```python
def __new__(cls, *paths):
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## __repr__

```python
def __repr__(self) -> str:
    """
    String representation of the converter state.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## __rshift__

```python
def __rshift__(self, target: Union[str, Path]) -> "Convert":
    """
    Overload the '>>' operator to convert a file or directory.

Args:
    target: The target path for conversion. Can be:
           - A file path with extension (converts to that format)
           - A directory path (keeps original names, changes format if specified)
           - A format string (e.g., ".pdf" applies format to all files)

Returns:
    Convert: A new Convert instance with the conversion results,
            allowing for chaining operations.

Example:
    Convert("input.txt") >> "output.pdf" >> "final_output/"
    Convert() >> "data.csv" >> "data.json"
    Convert("file1.doc", "file2.doc") >> ".pdf" >> "processed/"
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## async_convert

```python
async def async_convert(self, path: str = None, output_path: str = None, options: Optional[Options] = None) -> Any:
    """
    Asynchronously convert a file or directory to text.
    """
```
* **Async:** True
* **Method:** True
* **Class:** Convert

## can_convert

```python
def can_convert(self, path: str = None, options: Optional[Options] = None) -> bool:
    """
    Check if the file can be converted.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## convert

```python
def convert(self, path: str = None, output_path: str = None, options: Optional[Options] = None) -> Any:
    """
    Convert a file or directory to text.

Args:
    path: The path to the file to convert.
    output_path: The path to save the converted file.
    options: Conversion options.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## convert_and_compress

```python
def convert_and_compress(self, path: str = None, output_path: str = None, options: Optional[Options] = None) -> Any:
    """
    Convert a file or directory to text and compress the output to an archival format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## dry_run

```python
def dry_run(self, path: str = None, options: Optional[dict[str, Any]] = None) -> Any:
    """
    Perform a dry run of the conversion process.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## estimate_file_count

```python
def estimate_file_count(self, path: str = None, recursive: bool = False) -> int:
    """
    Estimate the number of files in a directory that can potentially be converted.

Args:
    path: The path to the directory to convert. If None, uses the current target directory.
    recursive: Whether to walk through subdirectories. Default is False.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## estimate_size

```python
def estimate_size(self, path: str = None, recursive: bool = False) -> int:
    """
    Estimate the size of files in a directory that can potentially be converted.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## estimate_time

```python
def estimate_time(self, path: str = None, recursive: bool = False) -> float:
    """
    Estimate the time required to convert files in a directory that can potentially be converted.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## get_chain

```python
def get_chain(self) -> List[Tuple[Path, Optional[Path]]]:
    """
    Get the full conversion chain.

Returns:
    List of tuples containing (source, target) pairs for each conversion.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## get_outputs

```python
def get_outputs(self) -> List[Path]:
    """
    Get the current output files.

Returns:
    List of Path objects representing current outputs.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## glob

```python
def glob(self, pattern: str) -> list[Path]:
    """
    Search for and convert files matching the pattern in the target directory.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## iterconvert

```python
def iterconvert(self, path: str = None, recursive: bool = False) -> Any:
    """
    Iterate through files in a directory and convert them one by one.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## preview

```python
def preview(self, path: str = None, options: Optional[dict[str, Any]] = None) -> Any:
    """
    Preview first N bytes of conversion
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## rglob

```python
def rglob(self, pattern: str) -> list[Path]:
    """
    Recursively search for and convert files matching the pattern in the target directory.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## upload

```python
def upload(self, path: str = None, options: Optional[dict[str, Any]] = None) -> Any:
    """
    Upload a converted file or directory to a website.
NOTE: All credentials and configurations for the upload must be set in the options.

Options include:
- url: Custom URL to upload to.
- github: Upload to GitHub repository.
- s3: Upload to Amazon S3 bucket.
- gcs: Upload to Google Cloud Storage bucket.
- azure: Upload to Azure Blob Storage.
- huggingface: Upload to Hugging Face Hub.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert

## walk

```python
def walk(self, path: str = None, recursive: bool = False) -> None:
    """
    Walk through a directory and convert all files it encounters.

Args:
    path: The path to the directory to convert. If None, uses the current target directory.
    recursive: Whether to walk through subdirectories. Default is False.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Convert
