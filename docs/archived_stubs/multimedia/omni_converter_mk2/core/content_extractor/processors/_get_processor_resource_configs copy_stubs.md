# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/processors/_get_processor_resource_configs copy.py'

Files last updated: 1750757297.9178379

Stub file last updated: 2025-07-17 05:44:02

## get_processor_resource_configs

```python
def get_processor_resource_configs() -> Generator[dict[str, Any], None, None]:
    """
    Generator that yields resource configuration dictionaries for content processors.

Each resource configuration contains:
- supported_formats: Set of file extensions the processor can handle
- processor_name: Unique identifier for the processor
- dependencies: Dict of required Python packages/modules (name -> version or None)
- critical_resources: List of methods that must be available for core functionality
- optional_resources: List of methods that provide enhanced features but aren't required

Yields:
    dict: Resource configuration for each processor
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
