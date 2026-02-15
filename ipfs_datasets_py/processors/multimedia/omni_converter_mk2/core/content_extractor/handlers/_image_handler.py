"""
Image format handlers for the Omni-Converter using IoC pattern.

This module provides handlers for image formats like JPEG, PNG, GIF, WebP, and SVG
using dependency injection for better modularity and testability, without inheritance.
"""
from types_ import Configs, Logger, Any, Optional, Callable, MagicMock, SupportedFormats


class ImageHandler:
    """
    Framework class for handling image-based formats using IoC pattern.
    
    This class only contains orchestration logic and delegates all format-specific
    processing to injected processors via the resources dictionary.
    """
    
    def __init__(self, 
                 resources: dict[str, Callable], 
                 configs: Configs
                 ):
        """
        Initialize the image handler with injected dependencies.
        
        Args:
            resources: Dictionary of callable resources including processors and utilities.
            configs: Configuration settings.
        """
        self.resources = resources
        self.configs = configs

        # Extract required resources - fail fast if missing
        # NOTE Some of these processors may support related formats,
        # Example: pil processor handles jpeg, png, gif, webp
        self._raster_image_processor: Callable | MagicMock  = self.resources["raster_image_processor"]
        self._vector_image_processor: Callable | MagicMock = self.resources["vector_image_processor"]
        self._ocr_processor:          Callable | MagicMock = self.resources["ocr_processor"]

        # Extension sets
        self._format_extensions:       frozenset[str] = self.resources["format_extensions"]
        self._supported_formats:       frozenset[str] = self.resources["supported_formats"]
        self._vector_image_extensions: frozenset[str] = self.resources["vector_image_extensions"]
        self._raster_image_extensions: frozenset[str] = self.resources["raster_image_extensions"]

        self._logger: Logger = self.resources["logger"]
        self._splitext: Callable[[str], tuple[str,...]] = self.resources["splitext"]
        self._is_mock: Callable[[Any],bool] = self.resources["is_mock"]
        self._can_handle: Callable = self.resources["can_handle"]

    @property
    def capabilities(self) -> dict[str, Any]:
        return {
            'category': 'image',
            'preserves_structure': False,
            'extracts_metadata': True,
            'supports_ocr': True if not self._is_mock(self._ocr_processor) else False,
        }

    def can_handle(self, file_path: str, format_name: Optional[str] = None) -> bool:
        """
        Check if this handler can process the given file format.
        
        Args:
            file_path: Path to the file.
            format_name: Format of the file, if known.
            
        Returns:
            True if this handler can process the format, False otherwise.
        """
        return self._can_handle(self._supported_formats, self._format_extensions, file_path, format_name)

    
    def extract_content(self, file_path: str, format_name: str, options: dict[str, Any]) -> tuple[str, dict[str, Any], list[dict[str, Any]]] | None:
        """
        Extract content from an image file using the appropriate processor.
        
        Args:
            file_path: Path to the file.
            format_name: Format of the file.
            options: Processing options.
            
        Returns:
            Tuple of (text content, metadata, sections).
        """
        # Delegate to appropriate processor based on format
        match format_name:
            case format_name if format_name in self._vector_image_extensions: # 'svg' | 'eps' | 'ai'
                processor = self._vector_image_processor
            case format_name if format_name in self._raster_image_extensions: # 'jpeg' | 'png' | 'gif' | 'webp'
                processor = self._raster_image_processor
            case _:
                raise ValueError(f"Unsupported image format: {format_name}")

        # if not self._is_mock(self._ocr_processor):
        #     options.update({"ocr_processor": self._ocr_processor})

        # if self._is_mock(processor):
        #     return None

        try:
            # Call the processor class
            return processor(file_path, options)
        except Exception as e:
            self._logger.error(f"Error processing {format_name} file '{file_path}': {e}", exc_info=True)
            raise RuntimeError(f"Failed to process {format_name} file: {file_path}") from e
