from typing import Any, Annotated as Ann
from pathlib import Path

try:
    from pydantic import BaseModel, PositiveInt, FilePath, AfterValidator as AV, ConfigDict, Field, BeforeValidator as BV
except ImportError:
    raise ImportError("Pydantic is required for this module. Please install it using 'pip install pydantic'.")

def _string_to_file_path(value: str) -> FilePath:
    return Path(value)

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
    total_files: PositiveInt = 0
    successful_files: PositiveInt = 0
    failed_files: PositiveInt = 0
    current_file: Ann[FilePath, AV(_string_to_file_path)] = ""
    is_processing: bool = False

    model_config = ConfigDict(validate_assignment=True)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to a dictionary.
        
        Returns:
            A dictionary representation of the pipeline status.
        """
        return self.model_dump()

    def reset(self) -> None:
        """Reset current_file and is_processing to initial values."""
        # Suppress any validation errors when resetting these values
        object.__setattr__(self, 'current_file', "")
        object.__setattr__(self, 'is_processing', False)