"""
Vector Store Management Tools for MCP Server — thin wrapper.

Business logic lives in ``vector_store_management_engine.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .vector_store_management_engine import (  # noqa: F401
    VectorStoreManager,
    FAISS_AVAILABLE,
    QDRANT_AVAILABLE,
    ELASTICSEARCH_AVAILABLE,
    EMBEDDINGS_AVAILABLE,
)

logger = logging.getLogger(__name__)
_manager = VectorStoreManager()


async def create_vector_index(
    index_name: str,
    documents: List[Dict[str, Any]],
    backend: str = "faiss",
    vector_dim: int = 384,
    distance_metric: str = "cosine",
    index_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a comprehensive vector index for high-performance similarity search.

    Args:
        index_name: Unique identifier for the vector index.
        documents: List of dicts with 'text' and optional 'metadata' keys.
        backend: Backend system ('faiss', 'qdrant', 'elasticsearch').
        vector_dim: Embedding dimensionality (default 384).
        distance_metric: Similarity metric ('cosine', 'euclidean', 'dot_product').
        index_config: Backend-specific configuration parameters.

    Returns:
        Dict with 'status', 'index_name', 'backend', 'vector_count', etc.
    """
    try:
        return await _manager.create_index(
            index_name, documents, backend, vector_dim, distance_metric, index_config
        )
    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Error creating vector index: {e}")
        return {"status": "error", "error": str(e), "index_name": index_name, "backend": backend}


async def search_vector_index(
    index_name: str,
    query: str,
    backend: str = "faiss",
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Search a vector index for similar documents.

    Args:
        index_name: Name of the index to search.
        query: Query text to search for.
        backend: Vector store backend.
        top_k: Number of top results to return.
        filters: Optional filters for search.
        config: Backend-specific configuration.

    Returns:
        Dict with 'status', 'results', 'total_results', etc.
    """
    try:
        return await _manager.search_index(index_name, query, backend, top_k, filters, config)
    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Error searching vector index: {e}")
        return {"status": "error", "error": str(e), "index_name": index_name, "backend": backend}


async def list_vector_indexes(backend: str = "all") -> Dict[str, Any]:
    """
    List available vector indexes.

    Args:
        backend: Backend to list indexes for ('all', 'faiss', 'qdrant', 'elasticsearch').

    Returns:
        Dict with 'status' and 'indexes' mapping backend→list.
    """
    try:
        return _manager.list_indexes(backend)
    except OSError as e:
        logger.error(f"Error listing vector indexes: {e}")
        return {"status": "error", "error": str(e), "backend": backend}


async def delete_vector_index(
    index_name: str,
    backend: str = "faiss",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Delete a vector index.

    Args:
        index_name: Name of the index to delete.
        backend: Vector store backend.
        config: Backend-specific configuration.

    Returns:
        Dict with 'status' and 'message'.
    """
    try:
        return _manager.delete_index(index_name, backend, config)
    except (OSError, ValueError, RuntimeError) as e:
        logger.error(f"Error deleting vector index: {e}")
        return {"status": "error", "error": str(e), "index_name": index_name, "backend": backend}
