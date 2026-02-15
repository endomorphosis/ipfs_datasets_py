"""
OCR processing utilities.

This module contains functions for Optical Character Recognition (OCR) on images.
It wraps third-party OCR dependencies to make them swappable and isolate them from
the rest of the codebase.
"""
from typing import Any, Optional
from io import BytesIO

from logger import logger
from dependencies import dependencies
from supported_formats import SupportedFormats

def can_process(format_name: str) -> bool:
    """
    Check if OCR processing is available for the given format.
    
    Args:
        format_name: The format of the file.
        
    Returns:
        True if OCR is available for this format, False otherwise.
    """
    # OCR is supported for common image formats
    return format_name in SupportedFormats.SUPPORTED_IMAGE_FORMATS


def extract_text(
    data: str | bytes,
    options: Optional[dict[str, Any]] = None
) -> str:
    """
    Extract text from an image using OCR.
    
    Args:
        data: The image data as bytes, file path, or BytesIO.
        options: Optional OCR options.
            - language: OCR language code (default: 'eng')
            - include_boxes: Whether to include text bounding boxes (default: False)
        
    Returns:
        The extracted text.
        
    Raises:
        ValueError: If OCR is not available.
        Exception: If an error occurs during OCR.
    """
    language = options.get('language', 'eng') # TODO This should be dynamic somehow.

    try:
        # Extract text with pytesseract
        text = dependencies.pytesseract.image_to_string(data, lang=language)

        return text.strip()

    except Exception as e:
        logger.error(f"Error during OCR processing: {e}")
        raise


def extract_metadata(
    data: str | bytes, # NOTE This is technically not the true type, but we need it like this to match the protocol.
    options: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """
    Extract metadata from an image using OCR.

    Args:
        data: The image data as bytes, file path, or BytesIO.
        options: Optional OCR options.

    Returns:
        A dictionary containing metadata such as dimensions, format, and mode.

    Raises:
        ValueError: If the data cannot be processed as an image.
    """
    try:
        # Extract metadata
        metadata = {
            'format': data.format,
            'mode': data.mode,
            'size': data.size,  # (width, height)
        }
        return metadata

    except Exception as e:
        logger.error(f"Error extracting metadata: {e}")
        raise ValueError(f"Failed to extract metadata: {e}") from e

def extract_structure(
    data: str | bytes,
    options: Optional[dict[str, Any]] = None
) -> list[dict[str, Any]]:
    """
    Extract features from an image using OCR.
    
    Args:
        data: The image data as bytes, file path, or BytesIO.
        options: Optional OCR options.
            - language: OCR language code (default: 'eng')
            - include_boxes: Whether to include text bounding boxes (default: True)
        
    Returns:
        A list of sections with extracted features.
        
    Raises:
        ValueError: If OCR is not available.
        Exception: If an error occurs during OCR.
    """
    options = options or {}
    language = options.get('language', 'eng')

    try:
        features = []
        # Extract text with bounding boxes
        output_type = dependencies.pytesseract.Output.DICT
        data = dependencies.pytesseract.image_to_data(data, lang=language, output_type=output_type)

        # Create a section for text with confidence
        confidences = []
        for i, text in enumerate(data['text']):
            if text.strip():
                confidences.append({
                    'text': text,
                    'confidence': data['conf'][i],
                    'block_num': data['block_num'][i],
                    'line_num': data['line_num'][i]
                })

        if confidences:
            features.append({
                'type': 'ocr_confidence',
                'content': confidences
            })

        return features

    except Exception as e:
        logger.error(f"Error extracting OCR metadata with Pytesseract: {e}")
        raise


def _convert_to_pil_image(data: str | bytes) -> Any: # Image.Image
    """Convert data to a PIL Image object."""

    # Turn data into a BytesIO object first.
    data = BytesIO(data)
    match data:
        case BytesIO():
            try:
                return dependencies.pil.Image.open(data)
            except Exception as e:
                raise ValueError(f"Failed to open image using PIL: {e}") from e
        case _:
            raise ValueError(f"Unsupported data type: {type(data)}")

def process(
    data: str | bytes,
    options: Optional[dict[str, Any]] = {}
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """
    Process the image data and return text, metadata, and sections.

    Args:
        data: The image data as bytes, file path, or BytesIO.
        options: Optional OCR options.

    Returns:
        A tuple containing:
        - Extracted text
        - Metadata (empty dict for now)
        - List of sections with features
    """
    pil_image = _convert_to_pil_image(data)

    text = extract_text(pil_image, options)
    metadata = extract_metadata(pil_image, options)
    sections = extract_structure(pil_image, options)

    return text, metadata, sections
