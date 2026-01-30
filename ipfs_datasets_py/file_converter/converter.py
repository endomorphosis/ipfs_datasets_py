"""
Main FileConverter class for unified file conversion.

Uses pluggable backends to support gradual migration from external libraries
to native implementation.
"""

from pathlib import Path
from typing import Optional, Union, List, Literal
from dataclasses import dataclass
import anyio
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """
    Result of file conversion.
    
    Attributes:
        text: Extracted text content
        metadata: Additional metadata (title, author, format, etc.)
        backend: Which backend performed the conversion
        success: Whether conversion succeeded
        error: Error message if conversion failed
    """
    text: str
    metadata: dict
    backend: str
    success: bool
    error: Optional[str] = None


class FileConverter:
    """
    Unified file converter with pluggable backends.
    
    Phase 1: Uses omni_converter_mk2 and convert_to_txt_based_on_mime_type
    Phase 2+: Gradually adds native implementations
    
    Examples:
        # Auto-select best backend
        converter = FileConverter()
        result = await converter.convert('document.pdf')
        print(result.text)
        
        # Specify backend explicitly
        converter = FileConverter(backend='markitdown')
        result = await converter.convert('file.docx')
        
        # Batch processing
        converter = FileConverter()
        results = await converter.convert_batch(['f1.pdf', 'f2.docx'])
        
        # Synchronous wrapper
        converter = FileConverter()
        result = converter.convert_sync('document.pdf')
    """
    
    def __init__(
        self,
        backend: Literal['auto', 'omni', 'markitdown', 'native'] = 'auto',
        **options
    ):
        """
        Initialize file converter.
        
        Args:
            backend: Which backend to use
                - 'auto': Automatically choose best available backend
                - 'omni': Use omni_converter_mk2 (rich metadata, batch)
                - 'markitdown': Use convert_to_txt (fast, async, web)
                - 'native': Use native implementation (Phase 2+)
            **options: Backend-specific configuration options
        """
        self.backend_name = backend
        self.options = options
        self._backend = None
        logger.info(f"FileConverter initialized with backend: {backend}")
    
    def _get_backend(self):
        """
        Lazy-load backend on first use.
        
        Returns:
            Backend instance
        """
        if self._backend is not None:
            return self._backend
            
        if self.backend_name == 'auto':
            # Try backends in order of preference
            
            # 1. Try markitdown (fast, stable, good default)
            try:
                from .backends.markitdown_backend import MarkItDownBackend
                self._backend = MarkItDownBackend(**self.options)
                logger.info("Using MarkItDown backend (auto-selected)")
                return self._backend
            except ImportError as e:
                logger.debug(f"MarkItDown not available: {e}")
            
            # 2. Try omni (rich features)
            try:
                from .backends.omni_backend import OmniBackend
                self._backend = OmniBackend(**self.options)
                logger.info("Using Omni backend (auto-selected)")
                return self._backend
            except ImportError as e:
                logger.debug(f"Omni backend not available: {e}")
            
            # 3. Fall back to native (basic, always available)
            from .backends.native_backend import NativeBackend
            self._backend = NativeBackend(**self.options)
            logger.info("Using Native backend (auto-selected, limited formats)")
            
        elif self.backend_name == 'omni':
            from .backends.omni_backend import OmniBackend
            self._backend = OmniBackend(**self.options)
            logger.info("Using Omni backend (explicit)")
            
        elif self.backend_name == 'markitdown':
            from .backends.markitdown_backend import MarkItDownBackend
            self._backend = MarkItDownBackend(**self.options)
            logger.info("Using MarkItDown backend (explicit)")
            
        elif self.backend_name == 'native':
            from .backends.native_backend import NativeBackend
            self._backend = NativeBackend(**self.options)
            logger.info("Using Native backend (explicit)")
            
        else:
            raise ValueError(f"Unknown backend: {self.backend_name}")
            
        return self._backend
    
    async def convert(
        self,
        file_path: Union[str, Path],
        **kwargs
    ) -> ConversionResult:
        """
        Convert file to text asynchronously.
        
        Args:
            file_path: Path to file or URL to convert
            **kwargs: Backend-specific options
            
        Returns:
            ConversionResult with text and metadata
            
        Example:
            converter = FileConverter()
            result = await converter.convert('document.pdf')
            if result.success:
                print(result.text)
            else:
                print(f"Error: {result.error}")
        """
        backend = self._get_backend()
        logger.debug(f"Converting {file_path} with {backend.__class__.__name__}")
        return await backend.convert(file_path, **kwargs)
    
    def convert_sync(
        self,
        file_path: Union[str, Path],
        **kwargs
    ) -> ConversionResult:
        """
        Convert file to text synchronously.
        
        Convenience wrapper around async convert() for non-async code.
        
        Args:
            file_path: Path to file to convert
            **kwargs: Backend-specific options
            
        Returns:
            ConversionResult with text and metadata
            
        Example:
            converter = FileConverter()
            result = converter.convert_sync('document.pdf')
            print(result.text)
        """
        return anyio.from_thread.run(self.convert, file_path, **kwargs)
    
    async def convert_batch(
        self,
        file_paths: List[Union[str, Path]],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[ConversionResult]:
        """
        Convert multiple files concurrently.
        
        Args:
            file_paths: List of files to convert
            max_concurrent: Maximum number of concurrent conversions
            **kwargs: Backend-specific options
            
        Returns:
            List of ConversionResults (in same order as input)
            
        Example:
            converter = FileConverter()
            files = ['doc1.pdf', 'doc2.docx', 'doc3.html']
            results = await converter.convert_batch(files)
            successful = [r for r in results if r.success]
            print(f"Converted {len(successful)}/{len(files)} files")
        """
        limiter = anyio.CapacityLimiter(max_concurrent)
        results = []
        
        async def convert_with_limiter(path, index):
            async with limiter:
                try:
                    result = await self.convert(path, **kwargs)
                    results.append((index, result))
                except Exception as e:
                    logger.error(f"Error converting {path}: {e}")
                    results.append((index, ConversionResult(
                        text='',
                        metadata={},
                        backend=self.backend_name,
                        success=False,
                        error=str(e)
                    )))
        
        async with anyio.create_task_group() as tg:
            for i, path in enumerate(file_paths):
                tg.start_soon(convert_with_limiter, path, i)
        
        # Sort results by original order
        results.sort(key=lambda x: x[0])
        return [r[1] for r in results]
    
    def get_supported_formats(self) -> List[str]:
        """
        Get list of file formats supported by current backend.
        
        Returns:
            List of file extensions (e.g., ['pdf', 'docx', 'html'])
            
        Example:
            converter = FileConverter(backend='markitdown')
            formats = converter.get_supported_formats()
            print(f"Supports {len(formats)} formats: {', '.join(formats[:10])}")
        """
        backend = self._get_backend()
        return backend.get_supported_formats()
    
    def get_backend_info(self) -> dict:
        """
        Get information about current backend.
        
        Returns:
            Dict with backend name, version, and capabilities
            
        Example:
            converter = FileConverter()
            info = converter.get_backend_info()
            print(f"Using: {info['name']} v{info['version']}")
        """
        backend = self._get_backend()
        return {
            'name': backend.__class__.__name__,
            'backend_type': self.backend_name,
            'supported_formats': len(backend.get_supported_formats()),
        }
