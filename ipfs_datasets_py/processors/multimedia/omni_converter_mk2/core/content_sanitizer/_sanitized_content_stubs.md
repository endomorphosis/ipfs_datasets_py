# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_sanitizer/_sanitized_content.py'

Files last updated: 1751001469.6007767

Stub file last updated: 2025-07-17 05:40:08

## SanitizedContent

```python
@dataclass
class SanitizedContent:
    """
    Sanitized content from a file.

This class extends the base Content class with sanitization information.

Attributes:
    sanitization_applied (list[str]): list of sanitization techniques applied.
    removed_content (dict[str, Any]): Information about content that was removed.
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
    A dictionary representation of the sanitized content.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SanitizedContent
