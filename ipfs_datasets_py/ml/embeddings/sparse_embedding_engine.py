"""
Sparse Embedding Engine — redirect module (canonical copy in ipfs_datasets_py.embeddings).

This file exists for backward compatibility. All new code should import from:
  from ipfs_datasets_py.embeddings.sparse_embedding_engine import ...
"""

from ipfs_datasets_py.embeddings.sparse_embedding_engine import (  # noqa: F401
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
