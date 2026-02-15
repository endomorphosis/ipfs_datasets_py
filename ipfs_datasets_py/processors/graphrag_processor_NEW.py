"""
DEPRECATED: GraphRAG Processor module.

This module has been deprecated and moved to processors.specialized.graphrag.

.. deprecated:: 1.9.0
   This module is deprecated. Use UnifiedGraphRAGProcessor from 
   processors.specialized.graphrag instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor
    
    NEW:
        from ipfs_datasets_py.processors.specialized.graphrag import UnifiedGraphRAGProcessor
        
    Or use the adapter:
        from ipfs_datasets_py.processors.adapters import GraphRAGAdapter
"""

import warnings

warnings.warn(
    "processors.graphrag_processor is deprecated. "
    "Use processors.specialized.graphrag.UnifiedGraphRAGProcessor instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
from ipfs_datasets_py.processors.specialized.graphrag import (
    UnifiedGraphRAGProcessor as GraphRAGProcessor,
    GraphRAGConfiguration,
)

# For backward compatibility
__all__ = ['GraphRAGProcessor', 'GraphRAGConfiguration']
