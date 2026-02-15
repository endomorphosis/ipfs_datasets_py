from dataclasses import dataclass, field
import os
from typing import Any, Optional
import copy

@dataclass
class FormattedOutput:
    """
    Formatted output for writing to a file or displaying.
    
    This class represents the formatted output from processing a file,
    ready to be written to a file or displayed.
    
    Attributes:
        content (str): The formatted content.
        format (str): The format of the output.
        metadata (dict[str, Any]): Metadata about the output.
        output_path (str): The path where the output will be written.
    """
    content: str
    format: str
    metadata: dict[str, Any] = field(default_factory=dict)
    output_path: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, dict):
            raise TypeError(
                f"metadata must be a dictionary, got {type(self.metadata).__name__}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to a dictionary.
        
        Returns:
            A dictionary representation of the formatted output.
        """
        return copy.deepcopy({
            'content': self.content,
            'format': self.format,
            'metadata': self.metadata,
            'output_path': self.output_path
        })
    
    def write_to_file(self, 
                      output_path: Optional[str] = None, 
                      write_as_binary: Optional[bool] = None,
                      skip_empty: Optional[bool] = None
                    ) -> Optional[str]:
        """Write the formatted output to a file.
        
        Args:
            output_path: The path to write to. If None, the output_path attribute is used.
            write_as_binary: Write the text to the file in binary mode if True, otherwise in text mode.
                If None, defaults to True (binary mode).
            skip_empty: If True, skip writing if the content is empty. If None, uses the instance's skip_if_empty attribute.
            
        Returns:
            The path where the output was written.
            
        Raises:
            ValueError: If no output path is specified.
            IOError: If the file cannot be written.
        """
        path = output_path or self.output_path
        if not path:
            raise ValueError("No output path specified")
        
        # Skip empty files
        if skip_empty is not None:
            if skip_empty is True and self.content.strip():
                return None

        # Ensure directory exists
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

        # Determine write mode
        mode = 'wb' if write_as_binary or write_as_binary is None else 'w'
        
        # Write the output
        with open(path, 'wb') as f:
            f.write(self.content.encode('utf-8'))  # Must encode to bytes
        return path