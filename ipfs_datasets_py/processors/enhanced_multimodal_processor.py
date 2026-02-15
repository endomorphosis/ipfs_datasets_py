"""
DEPRECATED: Enhanced Multimodal Processor module.

This module has been deprecated and moved to processors.specialized.multimodal.

.. deprecated:: 1.9.0
   This module is deprecated. Use EnhancedMultiModalProcessor from 
   processors.specialized.multimodal instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.enhanced_multimodal_processor import EnhancedMultiModalProcessor
    
    NEW:
        from ipfs_datasets_py.processors.specialized.multimodal import EnhancedMultiModalProcessor

For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.enhanced_multimodal_processor is deprecated. "
    "Use processors.specialized.multimodal.EnhancedMultiModalProcessor instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.multimodal import (
        EnhancedMultiModalProcessor,
        ContentQualityMetrics,
        ProcessingContext,
    )
except ImportError:
    # If specialized.multimodal is not available, create stubs
    class EnhancedMultiModalProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "EnhancedMultiModalProcessor requires dependencies that are not installed."
            )
    
    class ContentQualityMetrics:
        pass
    
    class ProcessingContext:
        pass

__all__ = [
    'EnhancedMultiModalProcessor',
    'ContentQualityMetrics',
    'ProcessingContext',
]
