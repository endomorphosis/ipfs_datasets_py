# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/processors/processor_factory.py'

Files last updated: 1751246787.1407833

Stub file last updated: 2025-07-17 05:44:02

## _GenericProcessor

```python
class _GenericProcessor:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _MakeProcessor

```python
class _MakeProcessor:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _MakeProcessorCache

```python
class _MakeProcessorCache:
    """
    Cache for processors to avoid recreating them on every call.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _ProcessorResources

```python
class _ProcessorResources(TypedDict):
    """
    TypedDict defining the structure of processor resources.

Attributes:
    supported_formats: Set of formats supported by the processor.
    processor_name: Name of the processor.
    dependencies: Dictionary mapping dependency names to their instances
    critical_resources: List of critical callables required by the processor. 
    optional_resources: List of optional callables that enhance functionality
    logger: Logger instance for logging messages
    configs: Configs instance containing configuration settings
    dependency_priority: Optional list defining priority order of dependencies
    dependency_mapping: Optional mapping of resources to required dependencies
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __call__

```python
def __call__(self, data, options):
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## __call__

```python
def __call__(self) -> dict[str, Any]:
    """
    Get processors, creating them if not already cached.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessorCache

## __init__

```python
def __init__(self, resources: _ProcessorResources = None, configs: Configs = None):
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## __init__

```python
def __init__(self, resources: _ProcessorResources):
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessorCache

## __repr__

```python
def __repr__(self):
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## __str__

```python
def __str__(self):
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## _apply_cross_processor_dependencies

```python
def _apply_cross_processor_dependencies(processors: dict[str, Any], dependencies: list[tuple[str, str, str, str]]) -> dict[str, Any]:
    """
    Apply cross-processor dependencies by enhancing methods with other processors.

This utility function allows one processor to use capabilities from another processor
by wrapping the original method with enhanced functionality. The original method
is called first, then each result is processed by the target processor's method.

Args:
    processors (dict[str, Any]): Dictionary mapping processor names to processor instances.
    dependencies (list[tuple[str, str, str, str]]): list of dependency tuples, where each tuple contains:
    - source_proc_name (str): Name of the processor to enhance
    - source_method_name (str): Name of the method to enhance
    - target_proc_name (str): Name of the processor that provides enhancement
    - target_method_name (str): Name of the method that provides enhancement

Returns:
    dict[str, Any]: The processors dictionary with enhanced methods applied.

Raises:
    TypeError: If processors is not a dictionary or dependencies is not a list.

Example:
    >>> processors = {
    ...     "xlsx_processor": xlsx_proc,
    ...     "image_processor": image_proc
    ... }
    >>> dependencies = [
    ...     ("xlsx_processor", "extract_images", "image_processor", "process_image")
    ... ]
    >>> enhanced_processors = _apply_cross_processor_dependencies(processors, dependencies)
    >>> # Now xlsx_processor.extract_images() will use image_processor.process_image()
    >>> # to enhance each extracted image
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _convert_to_pascal_case

```python
@staticmethod
def _convert_to_pascal_case(string: str) -> str:
    """
    Convert a string to PascalCase.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## _get_callables_from_module

```python
def _get_callables_from_module(self, module: ModuleType) -> Optional[dict[str, Callable]]:
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## _get_processor_class_for_specific_mime_type

```python
def _get_processor_class_for_specific_mime_type(self) -> Any:
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## _get_python_files_from_directory

```python
@staticmethod
def _get_python_files_from_directory(directory: Path) -> dict[str, Path]:
    """
    Get all Python files in a directory.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## _get_supported_formats_from_resource_config

```python
def _get_supported_formats_from_resource_config(resource_config) -> set[str]:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _load_functions_from_file

```python
def _load_functions_from_file(self, paths: dict[str, Path], callables_dict: dict = {}):
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## _load_module_from_path

```python
def _load_module_from_path(self, path: Path, proc_name: str = None) -> ModuleType:
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## _make_mock

```python
def _make_mock(self) -> MagicMock:
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## _make_processor

```python
def _make_processor(resources: _ProcessorResources) -> Any:
    """
    Create a processor instance based on the provided resources.

Args:
    resources: Dictionary containing processor resources and configurations.

Returns:
    Processor instance with proper processor_info structure.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _mock_processor

```python
def _mock_processor(self, methods: dict[Union[str, tuple[str, Any]], str], supported_formats: set[str], processor_name: str) -> MagicMock:
    """
    Create a mock processor with specified methods.

Args:
    methods: Dictionary mapping method names to their categories
    supported_formats: Set of formats supported by the processor
    processor_name: Name of the processor being mocked
    
Returns:
    MagicMock: Mock processor with all specified methods
    """
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## can_process

```python
def can_process(self, file_path: str) -> bool:
    """
    Check if the processor can handle the given file format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## capabilities

```python
@property
def capabilities(self) -> dict[str, Any]:
    """
    Return the capabilities of the processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## clear_cache

```python
def clear_cache(self):
    """
    Clear the processor cache, forcing recreation on next call.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessorCache

## create_enhanced_method

```python
def create_enhanced_method(orig_method: Callable, enhance_method: Callable) -> Callable:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## enhanced_method

```python
@functools.wraps(orig_method)
def enhanced_method(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## extract_metadata

```python
def extract_metadata(self, data: str | bytes, options: Optional[dict[str, Any]]):
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## extract_structure

```python
def extract_structure(self, data: str | bytes, options: Optional[dict[str, Any]]):
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## extract_text

```python
def extract_text(self, data: str | bytes, options: Optional[dict[str, Any]]):
    """
    Extract text content from the provided data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## is_cached

```python
def is_cached(self) -> bool:
    """
    Check if processors are currently cached.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessorCache

## make_processors

```python
@staticmethod
def make_processors() -> dict[str, Any]:
    """
    Create all processor instances.

Returns:
    dict mapping processor names to processor instances
    """
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessorCache

## make_processors

```python
def make_processors():
    """
    Create all processor instances.

Returns:
    dict mapping processor names to processor instances
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## process

```python
def process(self, data: str | bytes, options: Optional[dict[str, Any]]):
    """
    Process the provided data and return text, metadata, and sections.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor

## processor

```python
def processor(self) -> Optional[Any]:
```
* **Async:** False
* **Method:** True
* **Class:** _MakeProcessor

## processor_available

```python
def processor_available(self) -> bool:
    """
    Check if the processor is available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** _GenericProcessor
