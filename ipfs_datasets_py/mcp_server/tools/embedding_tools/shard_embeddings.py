"""
Shard Embeddings MCP Tool — thin wrapper.

Business logic: ipfs_datasets_py.embeddings.shard_embeddings_engine
"""

from ipfs_datasets_py.embeddings.shard_embeddings_engine import (  # noqa: F401
    shard_embeddings_by_dimension,
    shard_embeddings_by_cluster,
    merge_embedding_shards,
)

__all__ = [
    "shard_embeddings_by_dimension",
    "shard_embeddings_by_cluster",
    "merge_embedding_shards",
]
