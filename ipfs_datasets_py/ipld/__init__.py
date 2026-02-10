"""
IPLD (InterPlanetary Linked Data) Module

This module provides tools for working with IPLD data structures,
which are the foundation of content-addressable storage in IPFS.

Main components:
- storage: Core storage functionality for IPLD blocks
- dag_pb: Implementation of the DAG-PB format
- optimized_codec: High-performance encoding/decoding for IPLD with batch processing
- vector_store: IPLD-based vector storage for embeddings with similarity search
- knowledge_graph: IPLD-based knowledge graph with entity and relationship modeling

These components provide the foundation for GraphRAG (Graph Retrieval Augmented Generation),
combining vector similarity search with knowledge graph traversal for enhanced retrieval
and reasoning capabilities.
"""

from __future__ import annotations

import warnings


warnings.warn(
    "ipfs_datasets_py.ipld is deprecated; use ipfs_datasets_py.data_transformation.ipld instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ipfs_datasets_py.data_transformation.ipld.storage import IPLDStorage
from ipfs_datasets_py.data_transformation.ipld.dag_pb import create_dag_node, parse_dag_node
from ipfs_datasets_py.data_transformation.ipld.optimized_codec import (
    OptimizedEncoder, OptimizedDecoder, BatchProcessor,
    create_batch_processor, optimize_node_structure
)

# Optional components: these can pull in heavy deps (e.g., numpy). Keep the
# package import-safe so modules that only need core storage can still import.
try:
    from ipfs_datasets_py.vector_stores.ipld import IPLDVectorStore, SearchResult
except Exception:  # pragma: no cover
    IPLDVectorStore = None  # type: ignore[assignment]
    SearchResult = None  # type: ignore[assignment]

try:
    from ipfs_datasets_py.knowledge_graphs.ipld import (
        IPLDKnowledgeGraph, Entity, Relationship
    )
except Exception:  # pragma: no cover
    IPLDKnowledgeGraph = None  # type: ignore[assignment]
    Entity = None  # type: ignore[assignment]
    Relationship = None  # type: ignore[assignment]

# Check if official implementations are available
try:
    from ipld_dag_pb import PBNode, PBLink
    HAVE_IPLD_DAG_PB = True
except ImportError:
    from ipfs_datasets_py.data_transformation.ipld.dag_pb import PBNode, PBLink
    HAVE_IPLD_DAG_PB = False

try:
    import ipld_car
    HAVE_IPLD_CAR = True
except ImportError:
    HAVE_IPLD_CAR = False

__all__ = [
    'IPLDStorage',
    'create_dag_node',
    'parse_dag_node',
    'PBNode',
    'PBLink',
    'OptimizedEncoder',
    'OptimizedDecoder',
    'BatchProcessor',
    'create_batch_processor',
    'optimize_node_structure',
    'IPLDVectorStore',
    'SearchResult',
    'IPLDKnowledgeGraph',
    'Entity',
    'Relationship',
    'HAVE_IPLD_DAG_PB',
    'HAVE_IPLD_CAR'
]
