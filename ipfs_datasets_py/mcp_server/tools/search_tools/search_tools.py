# src/mcp_server/tools/search_tools.py
"""
Search tools (thin MCP wrappers).

All search logic lives in ipfs_datasets_py.search.search_tools_api.
Each function below is a minimal async wrapper that unpacks MCP-style
parameters and delegates straight to the canonical implementation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from ipfs_datasets_py.search.search_tools_api import (
    faceted_search_from_parameters,
    semantic_search_from_parameters,
    similarity_search_from_parameters,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thin standalone wrappers (no ClaudeMCPTool class needed)
# ---------------------------------------------------------------------------

async def semantic_search(
    query: str,
    model: str = "sentence-transformers/all-MiniLM-L6-v2",
    top_k: int = 5,
    collection: str = "default",
    filters: Optional[Dict[str, Any]] = None,
    vector_service: Any = None,
) -> Dict[str, Any]:
    """Perform semantic search on vector embeddings.

    Args:
        query: Search query text.
        model: Embedding model identifier.
        top_k: Maximum number of results.
        collection: Collection name to search.
        filters: Optional metadata filters.
        vector_service: Optional vector service instance.

    Returns:
        Dict with search results.
    """
    try:
        return await semantic_search_from_parameters(
            vector_service=vector_service,
            query=query,
            model=model,
            top_k=top_k,
            collection=collection,
            filters=filters or {},
        )
    except Exception as exc:
        logger.error("semantic_search failed: %s", exc)
        raise


async def similarity_search(
    embedding: List[float],
    top_k: int = 10,
    threshold: float = 0.5,
    collection: str = "default",
    vector_service: Any = None,
) -> Dict[str, Any]:
    """Find similar embeddings based on a reference vector.

    Args:
        embedding: Reference embedding vector.
        top_k: Maximum number of results.
        threshold: Minimum similarity threshold (0-1).
        collection: Collection name to search.
        vector_service: Optional vector service instance.

    Returns:
        Dict with similarity search results.
    """
    try:
        return await similarity_search_from_parameters(
            vector_service=vector_service,
            embedding=embedding,
            top_k=top_k,
            threshold=threshold,
            collection=collection,
        )
    except Exception as exc:
        logger.error("similarity_search failed: %s", exc)
        raise


async def faceted_search(
    query: str = "",
    facets: Optional[Dict[str, List[str]]] = None,
    aggregations: Optional[List[str]] = None,
    top_k: int = 20,
    collection: str = "default",
    vector_service: Any = None,
) -> Dict[str, Any]:
    """Perform faceted search with metadata filtering.

    Args:
        query: Optional search query text.
        facets: Facet filters keyed by field name.
        aggregations: Fields to aggregate on.
        top_k: Maximum number of results.
        collection: Collection name to search.
        vector_service: Optional vector service instance.

    Returns:
        Dict with faceted search results.
    """
    try:
        return await faceted_search_from_parameters(
            vector_service=vector_service,
            query=query,
            facets=facets or {},
            aggregations=aggregations or [],
            top_k=top_k,
            collection=collection,
        )
    except Exception as exc:
        logger.error("faceted_search failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Backward-compatible class aliases (kept so existing code that instantiates
# these classes still imports without error; they wrap the standalone fns)
# ---------------------------------------------------------------------------

class SemanticSearchTool:  # noqa: E302
    """Thin compatibility shim — wraps semantic_search()."""

    name = "semantic_search"

    def __init__(self, vector_service=None):
        self.vector_service = vector_service

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await semantic_search(vector_service=self.vector_service, **parameters)


class SimilaritySearchTool:
    """Thin compatibility shim — wraps similarity_search()."""

    name = "similarity_search"

    def __init__(self, vector_service=None):
        self.vector_service = vector_service

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await similarity_search(vector_service=self.vector_service, **parameters)


class FacetedSearchTool:
    """Thin compatibility shim — wraps faceted_search()."""

    name = "faceted_search"

    def __init__(self, vector_service=None):
        self.vector_service = vector_service

    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return await faceted_search(vector_service=self.vector_service, **parameters)
