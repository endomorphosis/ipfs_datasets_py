"""
Lightweight embeddings package — dependency-free core data models and utilities.

Heavy embedding models (torch, transformers, etc.) are in ipfs_datasets_py.ml.embeddings.
"""

from .sparse_embedding_engine import (
    SparseModel,
    SparseEmbedding,
    MockSparseEmbeddingService,
    get_default_sparse_service,
)

__all__ = [
    "SparseModel",
    "SparseEmbedding",
    "MockSparseEmbeddingService",
    "get_default_sparse_service",
]
