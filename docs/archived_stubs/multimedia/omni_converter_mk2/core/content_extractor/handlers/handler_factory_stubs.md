# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/handlers/handler_factory.py'

Files last updated: 1750460699.7586536

Stub file last updated: 2025-07-17 05:44:44

## ImageHandlerResources

```python
class ImageHandlerResources(TypedDict):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _create_application_handler

```python
def _create_application_handler(processors) -> ApplicationHandler:
    """
    Factory function to create an ApplicationHandler instance.

Returns:
    An instance of ApplicationHandler.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _create_audio_handler

```python
def _create_audio_handler(processors):
    """
    Factory function to create an AudioHandler instance.

Returns:
    An instance of AudioHandler.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _create_image_handler

```python
def _create_image_handler(processors):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _create_text_handler

```python
def _create_text_handler(processors):
    """
    Factory function to create a TextHandler instance.

Args:
    resources: Additional resources to provide.
    configs: Configuration settings.
    
Returns:
    An instance of TextHandler.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## _create_video_handler

```python
def _create_video_handler(processors):
    """
    Factory function to create a VideoHandler instance.

Returns:
    An instance of VideoHandler.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## make_all_handlers

```python
def make_all_handlers() -> dict[str, Callable]:
    """
    Create factory functions for all format handlers.

Args:
    resources: Optional additional resources to provide to handlers.
    configs: Configuration settings.
    
Returns:
    Dictionary mapping handler types to factory functions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
