"""
Embedding Tools for IPFS Datasets MCP Server

This module provides vector embedding generation tools: single-text embeddings,
batch embeddings, file-based embeddings, and access to the full list of
available embedding models.

Core functions: generate_embedding, generate_batch_embeddings,
generate_embeddings_from_file, get_available_tools, shard_embeddings.
"""
from .embedding_generation import (
    EmbeddingGenerationTool,
    BatchEmbeddingTool
)

__all__ = [
    'EmbeddingGenerationTool',
    'BatchEmbeddingTool'
]
