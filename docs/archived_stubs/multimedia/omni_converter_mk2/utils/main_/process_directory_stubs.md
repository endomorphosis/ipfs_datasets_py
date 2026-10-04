# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/utils/main_/process_directory.py'

Files last updated: 1751075895.058516

Stub file last updated: 2025-07-17 05:34:14

## _callback

```python
def _callback(current, total, current_file):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _estimate_file_count

```python
def _estimate_file_count(dir_path: str, recursive: bool) -> int:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## process_directory

```python
def process_directory(dir_path: str, output_dir: Optional[str] = None, options: Optional[dict[str, Any]] = None, show_progress: bool = True, recursive: bool = False) -> BatchResult:
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
* **Method:** False
* **Class:** N/A
