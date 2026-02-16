"""
DEPRECATED: Advanced Media Processing module.

This module has been deprecated and moved to processors.specialized.media.

.. deprecated:: 1.10.0
   This module is deprecated. Use AdvancedMediaProcessor from 
   processors.specialized.media instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.advanced_media_processing import AdvancedMediaProcessor
    
    NEW:
        from ipfs_datasets_py.processors.specialized.media import AdvancedMediaProcessor

For more information, see:
    docs/PROCESSORS_MIGRATION_GUIDE.md
    docs/PROCESSORS_COMPREHENSIVE_PLAN_2026.md
"""

import warnings

warnings.warn(
    "processors.advanced_media_processing is deprecated. "
    "Use processors.specialized.media.AdvancedMediaProcessor instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.media import (
        AdvancedMediaProcessor,
        MediaContent,
        TranscriptionResult,
    )
except ImportError as e:
    # Create stubs if import fails
    class AdvancedMediaProcessor:
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "AdvancedMediaProcessor requires dependencies that are not installed. "
                "Please install multimedia processing dependencies."
            )
    
    class MediaContent:
        pass
    
    class TranscriptionResult:
        pass

__all__ = [
    'AdvancedMediaProcessor',
    'MediaContent',
    'TranscriptionResult',
]
