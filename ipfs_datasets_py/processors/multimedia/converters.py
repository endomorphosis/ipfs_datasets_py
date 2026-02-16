"""
Unified Converter Interface for Multimedia Processing.

This module provides a unified facade over both converter systems:
- omni_converter_mk2 (modern plugin architecture, 342 files)
- convert_to_txt_based_on_mime_type (legacy monad system, 102 files)

The UnifiedConverter automatically routes to the best converter based on file format
and system availability. This provides a simple, consistent API while preserving
the underlying git submodule architecture.

## Usage

```python
from ipfs_datasets_py.processors.multimedia import UnifiedConverter

# Simple usage
converter = UnifiedConverter()
text = converter.convert_file("document.pdf")

# With format hint
text = converter.convert_file("image.png", format="png")

# Check available converters
formats = converter.supported_formats()
print(f"Supported: {formats}")
```

## Architecture

Both underlying systems are git submodules:
- omni_converter_mk2: https://github.com/endomorphosis/omni_converter_mk2
- convert_to_txt: https://github.com/endomorphosis/convert_to_txt_based_on_mime_type

This facade preserves the submodule structure while providing a unified API.
See docs/MULTIMEDIA_ARCHITECTURE_ANALYSIS.md for details.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Result of file conversion operation."""
    success: bool
    text: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    converter_used: Optional[str] = None


class ConverterRegistry:
    """
    Registry for tracking available converters and their capabilities.
    
    This provides auto-discovery and format routing without modifying
    the underlying git submodule code.
    """
    
    def __init__(self):
        self.omni_available = False
        self.legacy_available = False
        self._check_availability()
    
    def _check_availability(self):
        """Check which converter systems are available."""
        # Check omni_converter_mk2
        try:
            from . import omni_converter_mk2
            self.omni_available = True
            logger.info("omni_converter_mk2 available")
        except ImportError as e:
            logger.warning(f"omni_converter_mk2 not available: {e}")
        
        # Check convert_to_txt_based_on_mime_type
        try:
            from . import convert_to_txt_based_on_mime_type
            self.legacy_available = True
            logger.info("convert_to_txt_based_on_mime_type available")
        except ImportError as e:
            logger.warning(f"convert_to_txt_based_on_mime_type not available: {e}")
    
    def get_best_converter(self, file_path: str, format_hint: Optional[str] = None) -> str:
        """
        Determine which converter to use for a given file.
        
        Args:
            file_path: Path to file to convert
            format_hint: Optional format hint (e.g., "pdf", "png")
        
        Returns:
            "omni", "legacy", or "none"
        """
        if not self.omni_available and not self.legacy_available:
            return "none"
        
        # Get file extension
        ext = Path(file_path).suffix.lower().lstrip('.')
        format_to_check = format_hint or ext
        
        # Format-based routing logic
        # See docs/MULTIMEDIA_ARCHITECTURE_ANALYSIS.md for rationale
        
        # Text formats - either system works
        text_formats = ['txt', 'html', 'xml', 'json', 'csv', 'md', 'rst']
        if format_to_check in text_formats:
            return "omni" if self.omni_available else "legacy"
        
        # Document formats - prefer omni for newer formats
        doc_formats = ['pdf', 'docx', 'xlsx', 'pptx', 'odt']
        if format_to_check in doc_formats:
            return "omni" if self.omni_available else "legacy"
        
        # Image formats - prefer omni (more formats)
        image_formats = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp']
        if format_to_check in image_formats:
            return "omni" if self.omni_available else "legacy"
        
        # Audio/Video - prefer omni
        av_formats = ['mp3', 'wav', 'mp4', 'webm', 'avi', 'mkv', 'mov']
        if format_to_check in av_formats:
            return "omni" if self.omni_available else "legacy"
        
        # Default: prefer omni if available, fallback to legacy
        return "omni" if self.omni_available else "legacy"
    
    def supported_formats(self) -> Dict[str, List[str]]:
        """
        Get list of supported formats by converter.
        
        Returns:
            Dict mapping converter name to list of supported formats
        """
        formats = {}
        
        if self.omni_available:
            formats['omni'] = [
                'txt', 'html', 'xml', 'json', 'csv', 'pdf', 'docx', 'xlsx',
                'jpg', 'png', 'gif', 'webp', 'svg', 'mp3', 'wav', 'mp4', 'webm'
            ]
        
        if self.legacy_available:
            formats['legacy'] = [
                'txt', 'html', 'xml', 'json', 'csv', 'pdf', 'docx', 'xlsx',
                'jpg', 'png', 'mp3', 'mp4'
            ]
        
        return formats


class UnifiedConverter:
    """
    Unified interface to both converter systems.
    
    This facade provides a simple API while automatically routing to the
    best available converter based on file format. Both underlying systems
    (omni_converter_mk2 and convert_to_txt_based_on_mime_type) remain as
    git submodules.
    
    ## Usage
    
    ```python
    converter = UnifiedConverter()
    
    # Convert file
    result = converter.convert_file("document.pdf")
    if result.success:
        print(result.text)
    
    # Check supported formats
    formats = converter.supported_formats()
    ```
    
    ## Adapter Pattern
    
    This class acts as an adapter/facade over the two converter systems:
    - Preserves git submodule structure (no upstream changes)
    - Provides consistent API regardless of underlying system
    - Auto-routes based on format and availability
    - Handles import errors gracefully
    """
    
    def __init__(self):
        """Initialize unified converter with registry."""
        self.registry = ConverterRegistry()
        self._omni_adapter = None
        self._legacy_adapter = None
    
    def convert_file(
        self,
        file_path: Union[str, Path],
        format: Optional[str] = None,
        **kwargs
    ) -> ConversionResult:
        """
        Convert file to text using best available converter.
        
        Args:
            file_path: Path to file to convert
            format: Optional format hint (e.g., "pdf", "png")
            **kwargs: Additional arguments passed to underlying converter
        
        Returns:
            ConversionResult with text, metadata, and status
        
        Example:
            ```python
            result = converter.convert_file("document.pdf")
            if result.success:
                print(f"Extracted {len(result.text)} characters")
            else:
                print(f"Error: {result.error}")
            ```
        """
        file_path = str(file_path)
        
        # Check file exists
        if not os.path.exists(file_path):
            return ConversionResult(
                success=False,
                error=f"File not found: {file_path}"
            )
        
        # Determine best converter
        converter_name = self.registry.get_best_converter(file_path, format)
        
        if converter_name == "none":
            return ConversionResult(
                success=False,
                error="No converters available. Install omni_converter_mk2 or convert_to_txt_based_on_mime_type."
            )
        
        # Route to appropriate converter
        try:
            if converter_name == "omni":
                return self._convert_with_omni(file_path, **kwargs)
            else:
                return self._convert_with_legacy(file_path, **kwargs)
        except Exception as e:
            logger.error(f"Conversion failed: {e}")
            return ConversionResult(
                success=False,
                error=str(e),
                converter_used=converter_name
            )
    
    def _convert_with_omni(self, file_path: str, **kwargs) -> ConversionResult:
        """
        Convert using omni_converter_mk2.
        
        Note: This is a stub adapter. Full implementation would import
        and call the actual omni_converter_mk2 API.
        """
        # TODO: Implement actual omni_converter_mk2 adapter
        # from .omni_converter_mk2.interfaces import OmniConverter
        # converter = OmniConverter()
        # result = converter.convert(file_path, **kwargs)
        
        logger.info(f"Would convert {file_path} with omni_converter_mk2")
        return ConversionResult(
            success=False,
            error="omni_converter_mk2 adapter not yet implemented (stub)",
            converter_used="omni"
        )
    
    def _convert_with_legacy(self, file_path: str, **kwargs) -> ConversionResult:
        """
        Convert using convert_to_txt_based_on_mime_type.
        
        Note: This is a stub adapter. Full implementation would import
        and call the actual convert_to_txt API.
        """
        # TODO: Implement actual convert_to_txt adapter
        # from .convert_to_txt_based_on_mime_type import ConversionPipeline
        # pipeline = ConversionPipeline()
        # result = pipeline.convert(file_path, **kwargs)
        
        logger.info(f"Would convert {file_path} with convert_to_txt_based_on_mime_type")
        return ConversionResult(
            success=False,
            error="convert_to_txt adapter not yet implemented (stub)",
            converter_used="legacy"
        )
    
    def supported_formats(self) -> Dict[str, List[str]]:
        """
        Get dict of supported formats by converter.
        
        Returns:
            Dict mapping converter names to list of supported formats
        
        Example:
            ```python
            formats = converter.supported_formats()
            print(f"omni supports: {formats.get('omni', [])}")
            print(f"legacy supports: {formats.get('legacy', [])}")
            ```
        """
        return self.registry.supported_formats()
    
    def is_format_supported(self, format: str) -> bool:
        """
        Check if a format is supported by any converter.
        
        Args:
            format: File format (e.g., "pdf", "png")
        
        Returns:
            True if format is supported by at least one converter
        """
        all_formats = self.supported_formats()
        for converter_formats in all_formats.values():
            if format.lower() in [f.lower() for f in converter_formats]:
                return True
        return False


# Convenience function
def convert_file(file_path: Union[str, Path], **kwargs) -> ConversionResult:
    """
    Convenience function to convert a file using the unified converter.
    
    Args:
        file_path: Path to file to convert
        **kwargs: Additional arguments passed to converter
    
    Returns:
        ConversionResult with text and metadata
    
    Example:
        ```python
        from ipfs_datasets_py.processors.multimedia.converters import convert_file
        
        result = convert_file("document.pdf")
        if result.success:
            print(result.text)
        ```
    """
    converter = UnifiedConverter()
    return converter.convert_file(file_path, **kwargs)


__all__ = [
    "UnifiedConverter",
    "ConverterRegistry",
    "ConversionResult",
    "convert_file"
]
