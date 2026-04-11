"""Compatibility wrapper for retrieval primitives.

Prefer importing these helpers from :mod:`ipfs_datasets_py.processors.retrieval`.
"""

from ..retrieval import (
    bm25_search_documents,
    build_bm25_index,
    embed_query_for_backend,
    embed_texts_with_router_or_local,
    hashed_term_projection,
    search_bm25_index,
    tokenize_lexical_text,
    vector_dot,
)

__all__ = [
    "bm25_search_documents",
    "build_bm25_index",
    "embed_query_for_backend",
    "embed_texts_with_router_or_local",
    "hashed_term_projection",
    "search_bm25_index",
    "tokenize_lexical_text",
    "vector_dot",
]
