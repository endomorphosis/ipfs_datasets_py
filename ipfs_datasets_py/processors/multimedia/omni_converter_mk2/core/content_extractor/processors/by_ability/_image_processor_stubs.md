# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/processors/by_ability/_image_processor.py'

Files last updated: 1751406732.699918

Stub file last updated: 2025-07-17 05:45:32

## ImageProcessor

```python
class ImageProcessor:
    """
    Interface for image processors.

Example Output:
    ```
    # Images
    ## Bnuy1
    - Image: Bnuy1.png
    - Dimensions: 800x600 pixels
    - Summary: This is a rabbit running in a clear-cut forest. The ocean is visible and reflects a golden sunset. A stylized message is visible in the sky.
    - Text: "It's not a rabbit, it's a Bnuy!"
    ```
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, resources: dict[str, Callable] = None, configs = None) -> None:
    """
    Initialize the image processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor

## can_process

```python
def can_process(self, format_name: str) -> bool:
    """
    Check if this processor can handle the given format.

Args:
    format_name: The name of the format to check.
    
Returns:
    True if this processor can handle the format, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor

## extract_images

```python
def extract_images(self, data: bytes, options: dict[str, Any]) -> list[BinaryIO]:
    """
    Extract images from a document or image file.

Args:
    data: The binary data of the document or image file.
    options: Processing options.
    
Returns:
    A list of binary streams containing extracted images.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor

## extract_metadata

```python
def extract_metadata(self, data: bytes, options: dict[str, Any]) -> dict[str, Any]:
    """
    Extract metadata from an image.

Args:
    data: The binary data of the image.
    options: Processing options.
    
Returns:
    Metadata extracted from the image.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor

## extract_summary

```python
def extract_summary(self, data: bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract visual features from an image.

Args:
    data: The binary data of the image.
    options: Processing options.
    
Returns:
    A list of features extracted from the image.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor

## extract_text

```python
def extract_text(self, data: bytes, options: dict[str, Any]) -> str:
    """
    Extract text from an image using OCR.

Args:
    data: The binary data of the image.
    options: Processing options.
    
Returns:
    Extracted text from the image.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor

## get_processor_info

```python
def get_processor_info(self) -> dict[str, Any]:
    """
    Get information about this processor.

Returns:
    A dictionary containing information about this processor, such as name, version,
    supported formats, and any other relevant metadata.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor

## process_image

```python
def process_image(self, data: bytes, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process an image completely, extracting text, metadata, and features.

Args:
    data: The binary data of the image.
    options: Processing options.
    
Returns:
    A tuple of (text content, metadata, sections).
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor

## supported_formats

```python
@property
def supported_formats(self) -> list[str]:
    """
    Get the list of formats supported by this processor.

Returns:
    A list of format names supported by this processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ImageProcessor
