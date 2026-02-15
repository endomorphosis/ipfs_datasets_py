"""
DEPRECATED: GraphRAG Processor module.

This module has been deprecated and consolidated into processors.specialized.graphrag.

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

For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
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

# Alias for backward compatibility
MockGraphRAGProcessor = GraphRAGProcessor

def create_graphrag_processor(*args, **kwargs):
    """Deprecated: Use UnifiedGraphRAGProcessor directly."""
    warnings.warn(
        "create_graphrag_processor is deprecated. Create UnifiedGraphRAGProcessor directly.",
        DeprecationWarning,
        stacklevel=2
    )
    return GraphRAGProcessor(*args, **kwargs)

def create_mock_processor(*args, **kwargs):
    """Deprecated: Use UnifiedGraphRAGProcessor directly."""
    warnings.warn(
        "create_mock_processor is deprecated. Create UnifiedGraphRAGProcessor directly.",
        DeprecationWarning,
        stacklevel=2
    )
    return MockGraphRAGProcessor(*args, **kwargs)

__all__ = [
    'GraphRAGProcessor',
    'MockGraphRAGProcessor', 
    'GraphRAGConfiguration',
    'create_graphrag_processor',
    'create_mock_processor',
]
