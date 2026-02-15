# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/batch_processor/batch_processor_factory.py'

Files last updated: 1752752181.9942064

Stub file last updated: 2025-07-17 04:40:25

## _BatchProcessorResources

```python
class _BatchProcessorResources(TypedDict):
    """
    TypedDict for BatchProcessor resources.

Attributes:
    processing_pipeline: Instance of ProcessingPipeline.
    error_monitor: Instance of ErrorMonitor.
    resource_monitor: Instance of ResourceMonitor.
    security_monitor: Instance of SecurityMonitor.
    logger: Logger instance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## make_async_batch_processor

```python
def make_async_batch_processor() -> AsyncBatchProcessor:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## make_batch_processor

```python
def make_batch_processor() -> BatchProcessor:
    """
    Make a BatchProcessor instance.

Returns:
    An instance of BatchProcessor.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
