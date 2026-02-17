"""
Knowledge Graph Extraction Module - Backward Compatibility Wrapper

⚠️ DEPRECATION NOTICE ⚠️
=========================
This module is DEPRECATED. All functionality has been moved to the extraction/ package.

Please update your imports to use the new location:

NEW (recommended):
    from ipfs_datasets_py.knowledge_graphs.extraction import (
        Entity,
        Relationship,
        KnowledgeGraph,
        KnowledgeGraphExtractor,
        KnowledgeGraphExtractorWithValidation
    )

OLD (deprecated, but still works):
    from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (
        Entity,
        Relationship,
        KnowledgeGraph,
        KnowledgeGraphExtractor,
        KnowledgeGraphExtractorWithValidation
    )

The extraction/ package provides a modular structure:
- extraction/entities.py: Entity class
- extraction/relationships.py: Relationship class
- extraction/graph.py: KnowledgeGraph class
- extraction/extractor.py: KnowledgeGraphExtractor class
- extraction/validator.py: KnowledgeGraphExtractorWithValidation class

This file remains only for backward compatibility and will be removed in a future version.
See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for migration instructions.
"""

import warnings

# Issue deprecation warning
warnings.warn(
    "The knowledge_graph_extraction module is deprecated. "
    "Use 'from ipfs_datasets_py.knowledge_graphs.extraction import ...' instead. "
    "See docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md for details.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export all classes from extraction package for backward compatibility
from ipfs_datasets_py.knowledge_graphs.extraction import (
    # Core classes
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphExtractor,
    KnowledgeGraphExtractorWithValidation,
    
    # Types
    EntityID,
    RelationshipID,
    EntityType,
    RelationshipType,
    DEFAULT_CONFIDENCE,
    MIN_CONFIDENCE,
    MAX_CONFIDENCE,
    
    # Integrations
    HAVE_TRACER,
    HAVE_ACCELERATE,
    WikipediaKnowledgeGraphTracer,
    AccelerateManager,
    is_accelerate_available,
    get_accelerate_status,
)

__all__ = [
    # Core classes
    'Entity',
    'Relationship',
    'KnowledgeGraph',
    'KnowledgeGraphExtractor',
    'KnowledgeGraphExtractorWithValidation',
    
    # Types
    'EntityID',
    'RelationshipID',
    'EntityType',
    'RelationshipType',
    'DEFAULT_CONFIDENCE',
    'MIN_CONFIDENCE',
    'MAX_CONFIDENCE',
    
    # Integrations
    'HAVE_TRACER',
    'HAVE_ACCELERATE',
    'WikipediaKnowledgeGraphTracer',
    'AccelerateManager',
    'is_accelerate_available',
    'get_accelerate_status',
]

__version__ = '0.1.0-deprecated'
__deprecated__ = True
__migration_guide__ = 'docs/KNOWLEDGE_GRAPHS_MIGRATION_GUIDE.md'
