# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/output_formatter/_output_formatter.py'

Files last updated: 1751370654.5768154

Stub file last updated: 2025-07-17 05:40:43

## OutputFormatter

```python
class OutputFormatter:
    """
    Output formatter for the Omni-Converter.

This class formats extracted normalized content into different output formats.

Attributes:
    resources (dict[str, Callable]): Dictionary of callable objects and dependencies.
    configs (Configs): Configuration settings.
    output_formats (dict[str, FormatterFunc]): Dictionary of formatter functions.
    default_format (str): The default output format.

Properties:
    available_formats (list[str]): List of available output formats.

Public Methods:
    format_output: Format normalized content for output in specified format.
    register_format: Register a new output format with formatter function.

Private Methods:
    _register_default_formatters: Register the default output formatters.
    _format_as_txt: Format normalized content as plain text.
    _format_as_json: Format normalized content as JSON.
    _format_as_markdown: Format normalized content as Markdown.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None) -> None:
    """
    Initialize an output formatter.

Args:
    resources: A dictionary of callable objects and dependencies.
    configs: A pydantic model containing configuration settings.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## _format_as_json

```python
def _format_as_json(self, output_dict: dict) -> str:
    """
    Format normalized content as JSON.

Args:
    output_dict: The normalized content to format.
    
Returns:
    The formatted normalized content as JSON.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## _format_as_markdown

```python
def _format_as_markdown(self, output_dict: dict) -> str:
    """
    Format normalized content as Markdown.

Args:
    output_dict: The normalized content to format.
    
Returns:
    The formatted normalized content as Markdown.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## _format_as_txt

```python
def _format_as_txt(self, output_dict: dict) -> str:
    """
    Format normalized content as plain text.

Args:
    normalized_content: The normalized content to format.
    
Returns:
    The formatted normalized content as plain text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## _json_serializer

```python
@staticmethod
def _json_serializer(obj):
    """
    JSON serializer for objects not serializable by default json code
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## _merge_into_metadata

```python
def _merge_into_metadata(self, normalized_content: Any) -> None:
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## _register_default_formatters

```python
def _register_default_formatters(self) -> None:
    """
    Register the default output formatters.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## available_formats

```python
@property
def available_formats(self) -> list[str]:
    """
    Get the available output formats.

Returns:
    List of available output formats.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## format_output

```python
def format_output(self, normalized_content: Content, format: Optional[str] = None, options: Optional[dict[str, Any]] = None, output_path: Optional[str] = None) -> FormattedOutput:
    """
    Format normalized content for output.

Args:
    normalized_content: The normalized content to format.
    format: The output format. If None, the default format is used.
    options: Optional formatting options.
    output_path: The path where the output will be written.
    
Returns:
    The formatted output.
    
Raises:
    ValueError: If the specified format is not supported.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## register_format

```python
def register_format(self, format_name: str, formatter: FormatterFunc) -> None:
    """
    Register an output format.

Args:
    format_name: The name of the format.
    formatter: The formatter function.
    
Raises:
    TypeError: If the formatter is not a callable function or has an incorrect signature.
    ValueError: If a formatter for the format already exists.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter
