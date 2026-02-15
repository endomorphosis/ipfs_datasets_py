# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/_recursive_serialize.py'

Files last updated: 1751411185.7342699

Stub file last updated: 2025-07-17 05:42:08

## _recursive_serialize

```python
def _recursive_serialize(obj: Any, _seen: set = None) -> Any:
    """
    Recursively serialize objects to JSON-compatible types.

Args:
    obj (Any): The object to serialize.
    _seen (set): Internal parameter to track seen objects for circular reference detection.

Returns:
    JSON-compatible representation of the object.

Raises:
    ValueError: If circular reference is detected.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
