"""
Adapter for omni_converter_mk2.

This backend wraps the omni_converter_mk2 library for rich metadata extraction
and comprehensive batch processing.

DEPRECATED: This backend is deprecated in favor of the native implementation.
Use FileConverter(backend='native') instead.
"""

from pathlib import Path
from typing import Union
import logging
from ..deprecation import warn_deprecated_backend

logger = logging.getLogger(__name__)


class OmniBackend:
    """
    Backend using omni_converter_mk2 for file conversion.
    
    Best for: Rich metadata extraction, batch processing, training data prep.
    """
    
    def __init__(self, **options):
        """
        Initialize Omni backend.
        
        DEPRECATED: Use NativeBackend instead for better performance and zero dependencies.
        
        Args:
            **options: Backend-specific options
        """
        # Issue deprecation warning
        warn_deprecated_backend('omni', alternative='native')
        
        self.options = options
        self._converter = None
        logger.debug("OmniBackend initialized (DEPRECATED)")
    
    def _get_converter(self):
        """Lazy-load converter on first use."""
        if self._converter is not None:
            return self._converter
        
        try:
            import sys
            omni_path = Path(__file__).parent.parent.parent / 'multimedia' / 'omni_converter_mk2'
            
            if not omni_path.exists():
                raise ImportError(f"omni_converter_mk2 submodule not found at {omni_path}")
            
            sys.path.insert(0, str(omni_path))
            
            # Import omni converter
            from interfaces.python_api import convert
            self._converter = convert
            logger.info("Using omni_converter_mk2 from submodule")
            return self._converter
            
        except ImportError as e:
            logger.error(f"Failed to import omni_converter_mk2: {e}")
            raise ImportError(
                f"omni_converter_mk2 not available: {e}\n"
                "Make sure the submodule is initialized: "
                "git submodule update --init ipfs_datasets_py/multimedia/omni_converter_mk2"
            )
    
    async def convert(self, file_path: Union[str, Path], **kwargs):
        """
        Convert file using omni_converter_mk2.
        
        Args:
            file_path: Path to file to convert
            **kwargs: Additional options
            
        Returns:
            ConversionResult with rich metadata
        """
        from ..converter import ConversionResult
        
        try:
            converter = self._get_converter()
            file_path = Path(file_path)
            
            if not file_path.exists():
                return ConversionResult(
                    text='',
                    metadata={},
                    backend='omni',
                    success=False,
                    error=f"File not found: {file_path}"
                )
            
            # Use omni's convert API
            # Note: omni_converter_mk2 is synchronous, wrap in async
            result = converter.this_file(str(file_path), to='txt')
            
            return ConversionResult(
                text=result.content if hasattr(result, 'content') else str(result),
                metadata=result.metadata if hasattr(result, 'metadata') else {},
                backend='omni',
                success=True
            )
            
        except Exception as e:
            logger.error(f"Omni conversion error for {file_path}: {e}")
            return ConversionResult(
                text='',
                metadata={},
                backend='omni',
                success=False,
                error=str(e)
            )
    
    def get_supported_formats(self):
        """Return list of supported formats."""
        # From omni_converter_mk2 documentation
        return [
            # Text formats
            'html', 'htm', 'xhtml', 'xml',
            'txt', 'text', 'plain', 'plaintext',
            'csv', 'ics', 'ical',
            
            # Image formats
            'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg',
            
            # Audio formats
            'mp3', 'mpeg', 'wav', 'wave',
            'ogg', 'oga', 'flac', 'aac',
            
            # Video formats
            'mp4', 'webm', 'avi', 'mkv', 'mov',
            
            # Application formats
            'pdf', 'json', 'docx', 'doc',
            'xlsx', 'xls', 'pptx', 'ppt',
            'zip',
        ]
