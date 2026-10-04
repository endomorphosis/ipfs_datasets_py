# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/text_normalizer/_normalized_content.py'

## NormalizedContent

```python
@dataclass
class NormalizedContent:
    """
    Normalized content from a file.

This class represents normalized content with normalization metadata.

Attributes:
    text (str): The normalized text content object.
    metadata (dict[str, Any]): Metadata about the content.
    normalized_by (list[str]): list of normalizers applied to the content.
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
    A dictionary representation of the normalized content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** NormalizedContent
