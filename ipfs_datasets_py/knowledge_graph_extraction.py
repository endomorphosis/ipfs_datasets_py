"""Backwards-compatible import shim for knowledge graph extraction.

The implementation lives in :mod:`ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction`.
This module preserves the historical import path used by tests and downstream code.
"""

from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (  # noqa: F401
    Entity,
    KnowledgeGraph,
    Relationship,
)

__all__ = [
    "Entity",
    "KnowledgeGraph",
    "Relationship",
]
