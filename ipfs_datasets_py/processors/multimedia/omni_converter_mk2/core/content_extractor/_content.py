from datetime import datetime
from typing import Any


try:
    from pydantic import BaseModel, Field, FilePath
except ImportError:
    raise ImportError("Pydantic is required for this module. Please install it using 'pip install pydantic'.")




class Content(BaseModel):
    """
    Content extracted from a file.
    
    Attributes:
        text (str): The extracted text content.
        metadata (dict): Metadata about the content.
        sections (list): Sections of the content (if applicable).
        source_format (str): The format of the source file.
        source_path (str): The path to the source file.
        extraction_time (datetime): The time the content was extracted.
    """
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[dict[str, Any]] = Field(default_factory=list)
    source_format: str = ""
    source_path: FilePath = ""
    extraction_time: datetime = Field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to a dictionary.

        Returns:
            A dictionary representation of the content.
        """
        # NOTE We intentionally don't used model_dump() in json mode
        # Because it excludes non-serializable types instead of converting them
        data = self.model_dump()
        data['extraction_time'] = self.extraction_time.isoformat()
        return data
