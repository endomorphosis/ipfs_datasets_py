"""
DEPRECATED: Multimodal Processor module.

This module has been deprecated and moved to processors.specialized.multimodal.

.. deprecated:: 1.9.0
   This module is deprecated. Use MultiModalContentProcessor from 
   processors.specialized.multimodal instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.multimodal_processor import MultiModalContentProcessor
    
    NEW:
        from ipfs_datasets_py.processors.specialized.multimodal import MultiModalContentProcessor
        
For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.multimodal_processor is deprecated. "
    "Use processors.specialized.multimodal.MultiModalContentProcessor instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.multimodal import (
        MultiModalContentProcessor,
        ProcessedContent,
        ProcessedContentBatch,
    )
except ImportError:
    # If specialized.multimodal is not available, create stubs
    class MultiModalContentProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "MultiModalContentProcessor requires dependencies that are not installed."
            )
    
    class ProcessedContent:
        pass
    
    class ProcessedContentBatch:
        pass

__all__ = [
    'MultiModalContentProcessor',
    'ProcessedContent',
    'ProcessedContentBatch',
]
