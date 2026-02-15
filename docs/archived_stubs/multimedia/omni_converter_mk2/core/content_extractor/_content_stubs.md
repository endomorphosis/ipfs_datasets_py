# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/_content.py'

Files last updated: 1752613982.7608109

Stub file last updated: 2025-07-17 05:42:08

## Content

```python
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
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## to_dict

```python
def to_dict(self) -> dict[str, Any]:
    """
    Convert to a dictionary.

Returns:
    A dictionary representation of the content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Content
