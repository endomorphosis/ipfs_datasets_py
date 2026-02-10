"""
Image processor interfaces for image format handlers.

This module provides specialized interfaces for image processors that handle
image formats like JPEG, PNG, GIF, WebP, SVG, etc.
"""
from typing import Any, Callable, BinaryIO
from unittest.mock import MagicMock


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

    def __init__(self, resources: dict[str, Callable] = None, configs=None) -> None:
        """Initialize the image processor."""
        self.configs = configs
        self.resources = resources

        self._supported_formats: set[str] = self.resources["formats"]
        self._processor_available: bool = self.resources["processor_available"]
        self._processor_name: str = self.resources["processor_name"]
        self._processor_versions: dict[str, str] = self.resources["processor_versions"]

        # NOTE Because each image format may require different methods,
        # we define the methods that will be used by the processor.
        self._get_version: Callable = self.resources["get_version"]
        self._extract_metadata: Callable = self.resources["extract_metadata"]
        self._extract_summary: Callable = self.resources["extract_structure"]
        self._extract_text: Callable = self.resources["extract_text"]
        self._open_image_file: Callable = self.resources["open_image_file"]


    def can_process(self, format_name: str) -> bool:
        """
        Check if this processor can handle the given format.
        
        Args:
            format_name: The name of the format to check.
            
        Returns:
            True if this processor can handle the format, False otherwise.
        """
        pass

    @property
    def supported_formats(self) -> list[str]:
        """
        Get the list of formats supported by this processor.
        
        Returns:
            A list of format names supported by this processor.
        """
        pass

    def get_processor_info(self) -> dict[str, Any]:
        """
        Get information about this processor.
        
        Returns:
            A dictionary containing information about this processor, such as name, version,
            supported formats, and any other relevant metadata.
        """
        pass

    def extract_text(self, data: bytes, options: dict[str, Any]) -> str:
        """
        Extract text from an image using OCR.
        
        Args:
            data: The binary data of the image.
            options: Processing options.
            
        Returns:
            Extracted text from the image.
        """
        pass

    def extract_metadata(self, data: bytes, options: dict[str, Any]) -> dict[str, Any]:
        """
        Extract metadata from an image.
        
        Args:
            data: The binary data of the image.
            options: Processing options.
            
        Returns:
            Metadata extracted from the image.
        """

    def extract_summary(self, data: bytes, options: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract visual features from an image.
        
        Args:
            data: The binary data of the image.
            options: Processing options.
            
        Returns:
            A list of features extracted from the image.
        """
        pass

    def process_image(self, data: bytes, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        """
        Process an image completely, extracting text, metadata, and features.
        
        Args:
            data: The binary data of the image.
            options: Processing options.
            
        Returns:
            A tuple of (text content, metadata, sections).
        """
        pass

    def extract_images(self, data: bytes, options: dict[str, Any]) -> list[BinaryIO]:
        """
        Extract images from a document or image file.
        
        Args:
            data: The binary data of the document or image file.
            options: Processing options.
            
        Returns:
            A list of binary streams containing extracted images.
        """
        pass
