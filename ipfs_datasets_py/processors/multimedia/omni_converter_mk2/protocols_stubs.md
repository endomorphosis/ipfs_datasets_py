# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/protocols.py'

Files last updated: 1751237590.903249

Stub file last updated: 2025-07-17 05:36:42

## ExtractMetadataFunction

```python
class ExtractMetadataFunction(Protocol):
    """
    Protocol for metadata extraction functions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ExtractSectionsFunction

```python
class ExtractSectionsFunction(Protocol):
    """
    Protocol for section extraction functions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ExtractTextFunction

```python
class ExtractTextFunction(Protocol):
    """
    Protocol for text extraction functions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ModuleWrapper

```python
class ModuleWrapper:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## NormalizerFunction

```python
@runtime_checkable
class NormalizerFunction(Protocol):
    """
    Protocol for normalizer functions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProcessFunction

```python
class ProcessFunction(Protocol):
    """
    Protocol for processor functions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Processor

```python
class Processor(Protocol):
    """
    Protocol for processor classes.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProcessorByAbility

```python
class ProcessorByAbility(Protocol):
    """
    Protocol for validator functions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProcessorByFormat

```python
class ProcessorByFormat(Protocol):
    """
    Protocol for processor functions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProcessorModuleProtocol

```python
@runtime_checkable
class ProcessorModuleProtocol(Protocol):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __call__

```python
def __call__(self, text: str) -> str:
    """
    Normalize text.

Args:
    text (str): The text to normalize.

Returns:
    str: The normalized text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** NormalizerFunction

## __call__

```python
def __call__(self, data: bytes | str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process data.

Args:
    data (bytes | str): The file content to process.
    options (dict[str, Any]): Processing options.
    
Returns:
    Tuple of (text content, metadata, sections).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessFunction

## __call__

```python
def __call__(self, data: bytes | str, options: dict[str, Any]) -> str:
    """
    Extract text from data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExtractTextFunction

## __call__

```python
def __call__(self, data: bytes | str, options: dict[str, Any]) -> dict[str, Any]:
    """
    Extract metadata from data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExtractMetadataFunction

## __call__

```python
def __call__(self, data: bytes | str, options: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract sections from data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ExtractSectionsFunction

## __call__

```python
def __call__(self, data: Any) -> None:
    """
    Validate data, raise exception if invalid.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessorByAbility

## __init__

```python
def __init__(self, module):
```
* **Async:** False
* **Method:** True
* **Class:** ModuleWrapper

## __init__

```python
def __init__(self, resources: dict[str, Callable], configs: BaseModel) -> None:
    """
    Process data and return (text, metadata, sections).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProcessorByFormat

## __init__

```python
def __init__(self, resources: dict[str, Callable], configs: BaseModel) -> None:
    """
    Process data and return (text, metadata, sections).
    """
```
* **Async:** False
* **Method:** True
* **Class:** Processor

## can_process

```python
def can_process(self, format_name: str) -> bool:
    """
    Check if this processor can handle the given format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Processor

## extract_metadata

```python
def extract_metadata(self, data: str, options: dict | None = None) -> dict:
```
* **Async:** False
* **Method:** True
* **Class:** ProcessorModuleProtocol

## extract_metadata

```python
def extract_metadata(self, data: bytes | str, options: dict[str, Any]) -> dict[str, Any]:
    """
    Extract metadata from data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Processor

## extract_structure

```python
def extract_structure(self, data: bytes | str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
```
* **Async:** False
* **Method:** True
* **Class:** ProcessorModuleProtocol

## extract_structure

```python
def extract_structure(self, data: bytes | str, options: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract sections from data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Processor

## extract_text

```python
def extract_text(self, data: str, options: dict | None = None) -> str:
```
* **Async:** False
* **Method:** True
* **Class:** ProcessorModuleProtocol

## extract_text

```python
def extract_text(self, data: bytes | str, options: dict[str, Any]) -> str:
    """
    Extract text from data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Processor

## get_processor_info

```python
def get_processor_info(self) -> dict[str, Any]:
    """
    Get information about this processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Processor

## process

```python
def process(self, data: Any, options: dict) -> tuple[str, dict, list]:
```
* **Async:** False
* **Method:** True
* **Class:** ProcessorModuleProtocol

## supported_formats

```python
@property
def supported_formats(self) -> list[str]:
    """
    Get the list of formats supported by this processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** Processor
