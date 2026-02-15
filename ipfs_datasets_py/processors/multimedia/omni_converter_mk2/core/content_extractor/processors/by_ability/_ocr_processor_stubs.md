# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/core/content_extractor/processors/by_ability/_ocr_processor.py'

Files last updated: 1749774803.9859543

Stub file last updated: 2025-07-17 05:45:32

## PyTesseractProcessor

```python
class PyTesseractProcessor(ImageProcessor):
    """
    Processor for extracting text from images using Tesseract OCR.

This processor uses pytesseract to perform OCR on images, extracting text,
metadata, and visual features.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
    """
    Initialize the PyTesseract processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PyTesseractProcessor

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
* **Class:** PyTesseractProcessor

## extract_features

```python
def extract_features(self, data: bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract visual features from an image.

Args:
    data: The binary data of the image.
    options: Processing options including:
        - include_hocr: Whether to include HOCR output (default: False)
        - include_boxes: Whether to include text bounding boxes (default: False)
        
Returns:
    A list of features extracted from the image.
    
Raises:
    ValueError: If pytesseract is not available or the image is invalid.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PyTesseractProcessor

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
    
Raises:
    ValueError: If PIL is not available or the image is invalid.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PyTesseractProcessor

## extract_text

```python
def extract_text(self, data: bytes, options: dict[str, Any]) -> str:
    """
    Extract text from an image using OCR.

Args:
    data: The binary data of the image.
    options: Processing options including:
        - language: OCR language (default: 'eng')
        - config: Additional Tesseract configuration
        
Returns:
    Extracted text from the image.
    
Raises:
    ValueError: If pytesseract is not available or the image is invalid.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PyTesseractProcessor

## get_processor_info

```python
def get_processor_info(self) -> dict[str, Any]:
    """
    Get information about this processor.

Returns:
    A dictionary containing information about this processor.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PyTesseractProcessor

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
    
Raises:
    ValueError: If pytesseract is not available or the image is invalid.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PyTesseractProcessor

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
* **Class:** PyTesseractProcessor
