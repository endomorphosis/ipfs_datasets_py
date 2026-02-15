# Function stubs from '/home/kylerose1946/omni_converter_mk2/core/_pipeline_status.py'

## PipelineStatus

```python
from pydantic import BaseModel
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
