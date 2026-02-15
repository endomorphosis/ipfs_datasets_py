
import os
from pathlib import Path 
from typing import Annotated


from pydantic import AfterValidator, BaseModel


from external_interface.file_paths_manager.supported_mime_types import SupportedMimeTypes


def validate_file_path(value: Path) -> Path:

    # Check if it's a file-type we have a converter for.
    if value.suffix not in SupportedMimeTypes:
        raise ValueError(f"File type '{value.suffix}' is not supported")

    # Check if the file exists.
    if not value.exists():
        raise ValueError(f"File '{value}' does not exist")

    # Check if we have read permissions for the file.
    if not os.access(value, os.R_OK):
        raise ValueError(f"Program lacks read permissions for File '{value}'")

    return value


class FilePath(BaseModel):
    """
    A model representing a file path.

    Attributes:
        file_path (Path): The path to the file. It must meet the following criteria:
        - The path must be a valid file path.
        - The file must exist in the input directory.
        - The file must be readable.
        - The file must be of a type we have a converter for.
        - The file's size must be under the memory limit allocated to the program.
    """
    file_path: Annotated[Path, AfterValidator(validate_file_path)]