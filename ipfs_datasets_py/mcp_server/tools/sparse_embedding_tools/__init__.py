"""
Sparse Embedding Tools for IPFS Datasets MCP Server

Provides BM25 and TF-IDF sparse vector embedding generation and indexing,
as well as hybrid sparse-dense search. Use these tools when exact keyword
matching matters alongside semantic similarity.

Core functions: generate_sparse_embedding, index_sparse_collection,
search_sparse_index, hybrid_search.
"""
# sparse_embedding_tools/__init__.py

from .sparse_embedding_tools import (
    generate_sparse_embedding,
    index_sparse_collection,
    sparse_search,
    manage_sparse_models,
    SparseModel,
    SparseEmbedding,
    MockSparseEmbeddingService
)

__all__ = [
    "generate_sparse_embedding",
    "index_sparse_collection", 
    "sparse_search",
    "manage_sparse_models",
    "SparseModel",
    "SparseEmbedding",
    "MockSparseEmbeddingService"
]
