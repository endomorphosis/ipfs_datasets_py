"""
DEPRECATED: GraphRAG Integrator module.

This module has been deprecated and consolidated into processors.specialized.graphrag.

.. deprecated:: 1.9.0
   This module is deprecated. Use GraphRAGIntegration from 
   processors.specialized.graphrag instead. This file will be removed 
   in v2.0.0 (August 2026).

Migration:
    OLD:
        from ipfs_datasets_py.processors.graphrag_integrator import GraphRAGIntegrator
    
    NEW:
        from ipfs_datasets_py.processors.specialized.graphrag import GraphRAGIntegration
        
For more information, see:
    docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md
"""

import warnings

warnings.warn(
    "processors.graphrag_integrator is deprecated. "
    "Use processors.specialized.graphrag.GraphRAGIntegration instead. "
    "This import will be removed in v2.0.0 (August 2026). "
    "See docs/PROCESSORS_REFACTORING_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Import from new location for backward compatibility
try:
    from ipfs_datasets_py.processors.specialized.graphrag.integration import (
        GraphRAGIntegration as GraphRAGIntegrator,
        # Import entity/relationship classes if they exist in integration
    )
except ImportError:
    # Fallback: import from specialized.graphrag package
    from ipfs_datasets_py.processors.specialized.graphrag import (
        GraphRAGIntegration as GraphRAGIntegrator,
    )

# For Entity, Relationship, KnowledgeGraph classes
# These need to be imported from the original integration.py or a new entity module
# For now, we'll note they may need special handling
try:
    from ipfs_datasets_py.processors.specialized.graphrag.integration import (
        Entity,
        Relationship,
        KnowledgeGraph,
    )
except (ImportError, AttributeError):
    # These classes may need to be kept or moved to a separate module
    # For now, create stub warnings
    class Entity:
        def __init__(self, *args, **kwargs):
            warnings.warn(
                "Entity class from graphrag_integrator is deprecated. "
                "Use classes from processors.specialized.graphrag instead.",
                DeprecationWarning
            )
    
    class Relationship:
        def __init__(self, *args, **kwargs):
            warnings.warn(
                "Relationship class from graphrag_integrator is deprecated.",
                DeprecationWarning
            )
    
    class KnowledgeGraph:
        def __init__(self, *args, **kwargs):
            warnings.warn(
                "KnowledgeGraph class from graphrag_integrator is deprecated.",
                DeprecationWarning
            )

def make_graphrag_integrator(*args, **kwargs):
    """Deprecated: Use GraphRAGIntegration directly."""
    warnings.warn(
        "make_graphrag_integrator is deprecated. Create GraphRAGIntegration directly.",
        DeprecationWarning,
        stacklevel=2
    )
    return GraphRAGIntegrator(*args, **kwargs)

__all__ = [
    'GraphRAGIntegrator',
    'Entity',
    'Relationship',
    'KnowledgeGraph',
    'make_graphrag_integrator',
]
