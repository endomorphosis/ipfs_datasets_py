# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/_pipeline_status.py'

Files last updated: 1751077413.4556248

Stub file last updated: 2025-07-17 05:39:35

## PipelineStatus

```python
class PipelineStatus(BaseModel):
    """
    Status of the processing pipeline.

This class represents the current status of the processing pipeline,
including statistics and the current state.

Attributes:
    total_files (int): Total number of files processed.
    successful_files (int): Number of files processed successfully.
    failed_files (int): Number of files that failed processing.
    current_file (str): Path to the file currently being processed.
    is_processing (bool): Whether the pipeline is currently processing a file.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _string_to_file_path

```python
def _string_to_file_path(value: str) -> FilePath:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## reset

```python
def reset(self) -> None:
    """
    Reset current_file and is_processing to initial values.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PipelineStatus

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary representation of the pipeline status.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PipelineStatus
