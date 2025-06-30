"""Vector store implementations for embeddings.

This module provides interfaces and implementations for various vector databases,
migrated and adapted from ipfs_embeddings_py.
"""

from .base import BaseVectorStore
from .qdrant_store import QdrantVectorStore
from .faiss_store import FAISSVectorStore

try:
    from .elasticsearch_store import ElasticsearchVectorStore
except ImportError:
    ElasticsearchVectorStore = None

__all__ = [
    'BaseVectorStore',
    'QdrantVectorStore', 
    'FAISSVectorStore',
    'ElasticsearchVectorStore'
]
