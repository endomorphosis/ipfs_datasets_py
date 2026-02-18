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
See docs/knowledge_graphs/MIGRATION_GUIDE.md for migration instructions.
"""

import warnings

# Issue deprecation warning
warnings.warn(
    "The knowledge_graph_extraction module is deprecated. "
    "Use 'from ipfs_datasets_py.knowledge_graphs.extraction import ...' instead. "
    "See docs/knowledge_graphs/MIGRATION_GUIDE.md for details.",
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
    KnowledgeGraphExtractorWithValidation as _NewKnowledgeGraphExtractorWithValidation,
    
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


class KnowledgeGraphExtractorWithValidation(_NewKnowledgeGraphExtractorWithValidation):
    """Backward-compatible wrapper for legacy API.

    The newer extraction package returns a detailed dict from
    `extract_knowledge_graph`. The legacy `knowledge_graph_extraction` API
    historically returned a `KnowledgeGraph` instance.
    """

    def extract_knowledge_graph(self, *args, **kwargs):  # type: ignore[override]
        result = super().extract_knowledge_graph(*args, **kwargs)
        if isinstance(result, dict) and "knowledge_graph" in result:
            return result["knowledge_graph"]
        return result

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
__migration_guide__ = 'docs/knowledge_graphs/MIGRATION_GUIDE.md'
