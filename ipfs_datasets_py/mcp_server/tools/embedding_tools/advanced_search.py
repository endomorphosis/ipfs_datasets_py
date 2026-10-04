"""
Advanced Search MCP Tool — thin wrapper.

Business logic: ipfs_datasets_py.embeddings.semantic_search_engine
"""

from ipfs_datasets_py.embeddings.semantic_search_engine import (  # noqa: F401
    semantic_search,
    multi_modal_search,
    hybrid_search,
    search_with_filters,
)

__all__ = [
    "semantic_search",
    "multi_modal_search",
    "hybrid_search",
    "search_with_filters",
]
