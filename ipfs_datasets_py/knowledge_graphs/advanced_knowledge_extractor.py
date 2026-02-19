"""
Advanced Knowledge Extractor — backward-compatibility shim.

The implementation has moved to
``ipfs_datasets_py.knowledge_graphs.extraction.advanced``.
This module re-exports all public names from that location so existing code
that imports from here continues to work without modification.

.. deprecated::
    Import from ``ipfs_datasets_py.knowledge_graphs.extraction.advanced``
    instead of this module.
"""
import warnings

warnings.warn(
    "ipfs_datasets_py.knowledge_graphs.advanced_knowledge_extractor is "
    "deprecated; import from "
    "ipfs_datasets_py.knowledge_graphs.extraction.advanced instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.knowledge_graphs.extraction.advanced import (  # noqa: F401, E402
    ExtractionContext,
    EntityCandidate,
    RelationshipCandidate,
    AdvancedKnowledgeExtractor,
)

__all__ = [
    "ExtractionContext",
    "EntityCandidate",
    "RelationshipCandidate",
    "AdvancedKnowledgeExtractor",
]
