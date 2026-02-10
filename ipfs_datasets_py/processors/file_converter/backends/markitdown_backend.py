"""
Adapter for convert_to_txt_based_on_mime_type / MarkItDown.

This backend wraps the MarkItDown library for file conversion.
Falls back to using the submodule if the package is not installed.

DEPRECATED: This backend is deprecated in favor of the native implementation.
Use FileConverter(backend='native') instead.
"""

from pathlib import Path
from typing import Union
import logging
from ..deprecation import warn_deprecated_backend

logger = logging.getLogger(__name__)


class MarkItDownBackend:
    """
    Backend using MarkItDown library for file conversion.
    
    This is the recommended default backend: fast, async-capable, broad format support.
    """
    
    def __init__(self, **options):
        """
        Initialize MarkItDown backend.
        
        DEPRECATED: Use NativeBackend instead for better performance and zero dependencies.
        
        Args:
            **options: Backend-specific options (currently unused)
        """
        # Issue deprecation warning
        warn_deprecated_backend('markitdown', alternative='native')
        
        self.options = options
        self._converter = None
        logger.debug("MarkItDownBackend initialized (DEPRECATED)")
    
    def _get_converter(self):
        """Lazy-load converter on first use."""
        if self._converter is not None:
            return self._converter
        
        # Try installed package first
        try:
            from markitdown import MarkItDown
            self._converter = MarkItDown()
            logger.info("Using installed MarkItDown package")
            return self._converter
        except ImportError:
            logger.debug("MarkItDown package not installed, trying submodule")
        
        # Try submodule
        try:
            import sys
            submodule_path = Path(__file__).parent.parent.parent / 'multimedia' / 'convert_to_txt_based_on_mime_type'
            if submodule_path.exists():
                sys.path.insert(0, str(submodule_path))
                from markitdown import MarkItDown
                self._converter = MarkItDown()
                logger.info("Using MarkItDown from submodule")
                return self._converter
        except ImportError as e:
            logger.error(f"Failed to import MarkItDown: {e}")
        
        raise ImportError(
            "MarkItDown not available. Install with: "
            "pip install markitdown  OR  "
            "pip install ipfs-datasets-py[file_conversion]"
        )
    
    async def convert(self, file_path: Union[str, Path], **kwargs):
        """
        Convert file using MarkItDown.
        
        Args:
            file_path: Path to file to convert
            **kwargs: Additional options
            
        Returns:
            ConversionResult
        """
        from ..converter import ConversionResult
        
        try:
            converter = self._get_converter()
            file_path = Path(file_path)
            
            if not file_path.exists():
                return ConversionResult(
                    text='',
                    metadata={},
                    backend='markitdown',
                    success=False,
                    error=f"File not found: {file_path}"
                )
            
            # MarkItDown has synchronous convert method
            result = converter.convert(str(file_path))
            
            return ConversionResult(
                text=result.text_content if hasattr(result, 'text_content') else str(result),
                metadata={'title': getattr(result, 'title', None)},
                backend='markitdown',
                success=True
            )
            
        except Exception as e:
            logger.error(f"MarkItDown conversion error for {file_path}: {e}")
            return ConversionResult(
                text='',
                metadata={},
                backend='markitdown',
                success=False,
                error=str(e)
            )
    
    def get_supported_formats(self):
        """Return list of supported formats."""
        # MarkItDown supports these formats (and more via plugins)
        return [
            'pdf', 'docx', 'xlsx', 'pptx',  # Office
            'html', 'xml', 'json', 'csv',    # Web/Data
            'md', 'txt', 'rst',              # Text
            'jpg', 'jpeg', 'png', 'gif',     # Images (with OCR)
            'mp3', 'wav', 'ogg',             # Audio (with transcription)
            'mp4', 'avi', 'mov',             # Video (metadata)
        ]
