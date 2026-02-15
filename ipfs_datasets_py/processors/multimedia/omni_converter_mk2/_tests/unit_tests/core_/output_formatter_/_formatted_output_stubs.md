# Function stubs from '/home/kylerose1946/omni_converter_mk2/core/output_formatter/_formatted_output.py'


# FormattedOutput Class

```python
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
```

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary representation of the formatted output.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FormattedOutput

## write_to_file

```python
def write_to_file(self, output_path: Optional[str] = None) -> str:
    """
    Write the formatted output to a file.

Args:
    output_path: The path to write to. If None, the output_path attribute is used.
    
Returns:
    The path where the output was written.
    
Raises:
    ValueError: If no output path is specified.
    IOError: If the file cannot be written.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FormattedOutput
