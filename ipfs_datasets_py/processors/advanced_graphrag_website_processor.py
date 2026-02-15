"""
DEPRECATED: Advanced GraphRAG Website Processor module.

This module has been deprecated and consolidated into processors.specialized.graphrag.

.. deprecated:: 1.9.0
   This module is deprecated. Use UnifiedGraphRAGProcessor from 
   processors.specialized.graphrag instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.advanced_graphrag_website_processor import AdvancedGraphRAGWebsiteProcessor
    
    NEW:
        from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor
        
For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.advanced_graphrag_website_processor is deprecated. "
    "Use processors.specialized.graphrag.UnifiedGraphRAGProcessor instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
from ipfs_datasets_py.processors.specialized.graphrag import (
    UnifiedGraphRAGProcessor as AdvancedGraphRAGWebsiteProcessor,
    GraphRAGConfiguration as WebsiteProcessingConfiguration,
)

# Result class alias - may need adjustment based on actual implementation
class AdvancedWebsiteResult:
    """Deprecated result class. Use the result from UnifiedGraphRAGProcessor instead."""
    def __init__(self, *args, **kwargs):
        warnings.warn(
            "AdvancedWebsiteResult is deprecated. Use result from UnifiedGraphRAGProcessor.",
            DeprecationWarning
        )
        # Store any data passed in
        self.__dict__.update(kwargs)

def demonstrate_advanced_processor():
    """Deprecated demo function."""
    warnings.warn(
        "demonstrate_advanced_processor is deprecated.",
        DeprecationWarning,
        stacklevel=2
    )
    print("This demo function is deprecated. Use UnifiedGraphRAGProcessor directly.")

__all__ = [
    'AdvancedGraphRAGWebsiteProcessor',
    'WebsiteProcessingConfiguration',
    'AdvancedWebsiteResult',
    'demonstrate_advanced_processor',
]
