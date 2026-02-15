"""
DEPRECATED: Website GraphRAG Processor module.

This module has been deprecated and consolidated into processors.specialized.graphrag.

.. deprecated:: 1.9.0
   This module is deprecated. Use WebsiteGraphRAGSystem from 
   processors.specialized.graphrag instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.website_graphrag_processor import WebsiteGraphRAGProcessor
    
    NEW:
        from ipfs_datasets_py.processors.specialized.graphrag import WebsiteGraphRAGSystem
        
For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.website_graphrag_processor is deprecated. "
    "Use processors.specialized.graphrag.WebsiteGraphRAGSystem instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
from ipfs_datasets_py.processors.specialized.graphrag import (
    WebsiteGraphRAGSystem as WebsiteGraphRAGProcessor,
)

# Configuration class alias
try:
    from ipfs_datasets_py.processors.specialized.graphrag import (
        GraphRAGConfiguration as WebsiteProcessingConfig,
    )
except ImportError:
    # Fallback to a simple class if config doesn't exist
    class WebsiteProcessingConfig:
        def __init__(self, *args, **kwargs):
            warnings.warn(
                "WebsiteProcessingConfig is deprecated. Use GraphRAGConfiguration instead.",
                DeprecationWarning
            )

def _default_config():
    """Deprecated: Use GraphRAGConfiguration directly."""
    warnings.warn(
        "_default_config is deprecated. Use GraphRAGConfiguration() directly.",
        DeprecationWarning,
        stacklevel=2
    )
    return WebsiteProcessingConfig()

__all__ = [
    'WebsiteGraphRAGProcessor',
    'WebsiteProcessingConfig',
]
