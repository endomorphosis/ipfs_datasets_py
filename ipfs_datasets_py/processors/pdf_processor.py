"""
DEPRECATED: PDF Processor module.

This module has been deprecated and moved to processors.specialized.pdf.

.. deprecated:: 1.9.0
   This module is deprecated. Use PDFProcessor from 
   processors.specialized.pdf instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.pdf_processor import PDFProcessor
    
    NEW:
        from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
        
    Or use the adapter:
        from ipfs_datasets_py.processors.adapters import PDFAdapter

For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.pdf_processor is deprecated. "
    "Use processors.specialized.pdf.PDFProcessor instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.pdf import (
        PDFProcessor,
        InitializationError,
        DependencyError,
    )
except ImportError:
    # If specialized.pdf is not available, create stubs
    class PDFProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "PDFProcessor requires dependencies that are not installed. "
                "Please install required packages."
            )
    
    class InitializationError(RuntimeError):
        pass
    
    class DependencyError(RuntimeError):
        pass

__all__ = [
    'PDFProcessor',
    'InitializationError',
    'DependencyError',
]
