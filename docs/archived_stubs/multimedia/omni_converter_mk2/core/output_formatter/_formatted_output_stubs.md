# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/output_formatter/_formatted_output.py'

Files last updated: 1751358699.823812

Stub file last updated: 2025-07-17 05:40:43

## FormattedOutput

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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __post_init__

```python
def __post_init__(self) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** FormattedOutput

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
def write_to_file(self, output_path: Optional[str] = None, write_as_binary: Optional[bool] = None, skip_empty: Optional[bool] = None) -> Optional[str]:
    """
    Write the formatted output to a file.

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
```
* **Async:** False
* **Method:** True
* **Class:** FormattedOutput
