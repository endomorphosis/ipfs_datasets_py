# Function stubs from '/home/kylerose1946/omni_converter_mk2/core/output_formatter/_output_formatter.py'

## OutputFormatter Class

```python
class OutputFormatter:
    """
    Output formatter for the Omni-Converter.

    This class formats extracted content into different output formats.

    Attributes:
        resources (dict[str, Callable]): Dictionary of callable objects and dependencies.
        configs (Configs): Configuration settings.
        output_formats (dict[str, FormatterFunc]): Dictionary of formatter functions.
        default_format (str): The default output format.

    Properties:
        available_formats (list[str]): List of available output formats.

    Public Methods:
        format_output: Format content for output in specified format.
        register_format: Register a new output format with formatter function.
    """
```

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

## _format_as_txt

```python
def _format_as_txt(self, content: Content) -> str:
    """
    Format content as plain text.

Args:
    content: The content to format.
    
Returns:
    The formatted content as plain text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## _format_as_json

```python
def _format_as_json(self, content: Content) -> str:
    """
    Format content as JSON.

Args:
    content: The content to format.
    
Returns:
    The formatted content as JSON.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## _format_as_markdown

```python
def _format_as_markdown(self, content: Content) -> str:
    """
    Format content as Markdown.

Args:
    content: The content to format.
    
Returns:
    The formatted content as Markdown.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OutputFormatter

## format_output

```python
def format_output(self, content: Content, format: Optional[str] = None, options: Optional[dict[str, Any]] = None, output_path: Optional[str] = None) -> FormattedOutput:
    """
    Format content for output.

Args:
    content: The content to format.
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
    ValueError: If a formatter for the format already exists.
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
