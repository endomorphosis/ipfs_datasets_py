# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/text_normalizer/_text_normalizer.py'

## TextNormalizer

```python
class TextNormalizer:
    """
    Text normalizer for the Omni-Converter.

Normalizes text from content objects by applying various normalization functions.

Attributes:
    resources (dict[str, Callable]): Dictionary of callable objects and dependencies.
    configs (Configs): Configuration settings containing paths and other config data.

Properties:
    applied_normalizers (list[str]): List of registered normalizer names.
    normalizers (dict[str, NormalizerFunction]): Dictionary of registered normalizer functions.

Methods:
    normalize_text: Normalize text content using specified normalizers.
    register_normalizer: Register a new normalizer function.
    register_normalizers_from: Register normalizers from a specified folder.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs: Configs = None):
    """
    Initialize a text normalizer instance.

Creates a TextNormalizer that can apply various text normalization functions
to content objects. The normalizer automatically discovers and registers
normalization functions from the configured directories during initialization.

Args:
    resources (dict[str, Callable]): A dictionary containing callable 
    objects and dependencies required by the normalizer, including:
    - 'importlib_util': Module for dynamic imports
    - 'normalized_content': Factory for creating NormalizedContent objects
    - 'logger': Logger instance for operation logging
    Defaults to None.
    configs (Configs): A pydantic model containing configuration 
    Must include paths.NORMALIZER_FUNCTIONS_DIR and paths.PLUGINS_DIR.
    Defaults to None.

Raises:
    TypeError: If resources is not a dictionary or configs is not provided.
    KeyError: If required keys are missing in the resources dictionary.
    AttributeError: If the required configs do not have the expected attributes.
    RuntimeError: If no normalizers could be loaded from the default or plugins folder.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextNormalizer

## register_normalizers_from

```python
def register_normalizers_from(self, folder: Path) -> None:
    """
    Registers all normalizer functions from Python modules in the specified folder.

This method dynamically loads Python modules from the given folder and registers
any functions that are instances of `NormalizerFunction`. It skips certain files
such as `__init__.py`, private modules (those starting with an underscore), or
modules that do not contain the word 'normalizer' in their name.

Args:
    folder (Path): The folder containing Python files to scan for normalizer functions.

Raises:
    RuntimeError: Any unexpected error occurs while loading a module.

Logging:
    - Logs the start and completion of the registration process.
    - Logs debug information for each module being loaded.
    - Logs errors for failed imports or registration attempts.
    - Logs warnings for individual normalizer registration failures.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextNormalizer

## normalize_text

```python
def normalize_text(self, content: "Content", normalizers: Optional[list[str]] = None, skip: bool = False) -> "NormalizedContent":
    """
    Normalize text content using specified or all available normalizer functions.

This method processes the text content from a Content object by applying a sequence
of normalization functions. Each normalizer transforms the text in a specific way,
such as cleaning whitespace, standardizing line endings, or normalizing Unicode
characters. The normalizers are applied sequentially, with each one operating on
the output of the previous normalizer.

Args:
    content (Content): The content object containing the text to be normalized.
    normalizers (Optional[list[str]]): A list of normalizer function names to apply in the specified order. 
        If None or not provided, all registered normalizers will be applied.
        Unknown normalizer names will be skipped with a warning logged.
    skip (bool): If True, skips the normalization process entirely.
        This is meant to allow for conditional skipping of normalization
        based on external conditions or configurations. Defaults to False.

Returns:
    NormalizedContent: A specialized content object that wraps the original content
             with additional metadata about which normalizers were successfully
             applied during the normalization process.

Raises:
    No exceptions are raised directly, but individual normalizer failures are logged
    as errors and those normalizers are skipped to allow processing to continue.

Note:
    - The original content object is modified in-place with the normalized text
    - Failed normalizers are logged but do not stop the overall process
    - The order of normalizers matters as they are applied sequentially
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextNormalizer

## register_normalizer

```python
def register_normalizer(self, name: str, normalizer: NormalizerFunction) -> None:
    """
    Register a normalizer function with the text normalizer.

This method adds a new normalizer function to the internal registry, allowing it
to be used during text normalization operations. The normalizer must conform to
the NormalizerFunction protocol, which requires it to accept a single string
argument and return a normalized string. If a normalizer with the same name already exists, 
it will be overwritten and a warning will be logged.

Args:
    name (str): A unique identifier for the normalizer function. This name will
           be used to reference the normalizer in normalization operations.
    normalizer (NormalizerFunction): A callable that implements the NormalizerFunction
                   protocol. Must accept a string input and return
                   a normalized string output.

Logs:
    Warning: Logs a warning if the normalizer doesn't implement NormalizerFunction
        protocol or if a normalizer with the same name already exists.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextNormalizer

## normalizers

```python
@property
def normalizers(self) -> dict[str, NormalizerFunction]:
    """
    Get the dictionary of registered normalizers.

Returns:
    dict: A dictionary where keys are normalizer names and values are the corresponding
          normalizer functions.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextNormalizer

## applied_normalizers

```python
@property
def applied_normalizers(self) -> list[str]:
    """
    Get the names of all registered normalizers.

Returns:
    list of normalizer names.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextNormalizer
