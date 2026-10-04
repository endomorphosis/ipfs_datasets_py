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
from .shard_embeddings_engine import (
    shard_embeddings_by_dimension,
    shard_embeddings_by_cluster,
    merge_embedding_shards,
)
from .semantic_search_engine import (
    semantic_search,
    multi_modal_search,
    hybrid_search,
    search_with_filters,
)
from .generation_engine import (
    generate_embedding,
    generate_batch_embeddings,
    generate_embeddings_from_file,
)
from .embeddings_engine import (
    AdvancedIPFSEmbeddings,
    EmbeddingConfig,
    ChunkingConfig,
)

__all__ = [
    # sparse embedding
    "SparseModel",
    "SparseEmbedding",
    "MockSparseEmbeddingService",
    "get_default_sparse_service",
    # shard engine
    "shard_embeddings_by_dimension",
    "shard_embeddings_by_cluster",
    "merge_embedding_shards",
    # semantic search engine
    "semantic_search",
    "multi_modal_search",
    "hybrid_search",
    "search_with_filters",
    # generation engine
    "generate_embedding",
    "generate_batch_embeddings",
    "generate_embeddings_from_file",
    # advanced embeddings engine
    "AdvancedIPFSEmbeddings",
    "EmbeddingConfig",
    "ChunkingConfig",
]
