"""Embedding Generation Module.

Handles embedding generation for text chunks using various
embedding models (sentence-transformers, etc.).

Current implementation: Imports from parent llm_optimizer.py
Future: Will contain extracted embedding logic
"""

from ipfs_datasets_py.processors.llm_optimizer import (
    extract_embedding_from_chunk,
    extract_embeddings_from_chunks,
    extract_embedding_from_nested_data,
    get_embedding_from_llm_document_chunks,
)

__all__ = [
    'extract_embedding_from_chunk',
    'extract_embeddings_from_chunks',
    'extract_embedding_from_nested_data',
    'get_embedding_from_llm_document_chunks',
]
