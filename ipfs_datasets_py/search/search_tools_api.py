"""Search tool APIs (package-level).

This module contains reusable core logic behind MCP-facing search tools.
The MCP layer should stay as a thin delegate that validates input and formats output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


async def semantic_search_from_parameters(
    *,
    vector_service: Any,
    query: str,
    model: str = "thenlper/gte-small",
    top_k: int = 5,
    collection: str = "default",
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Perform semantic search.

    If a compatible vector_service is provided, uses it; otherwise delegates
    to the real vector-store manager's search_vector_index. Raises an honest
    error if no index exists for the collection instead of fabricating results.
    """
    if vector_service:
        samples = [query]
        search_results = await vector_service.index_knn(samples, model)
        if search_results and isinstance(search_results, list):
            results: List[Dict[str, Any]] = search_results[:top_k]
        else:
            results = []
        return {
            "query": query,
            "model": model,
            "top_k": top_k,
            "collection": collection,
            "results": results,
            "total_found": len(results),
        }
    # No vector_service: use the genuine vector-store search. This embeds the
    # query with the real model and searches the FAISS index. If the collection
    # has no index, search_vector_index raises an honest error.
    if model != "thenlper/gte-small":
        raise ValueError("The local FAISS manager uses thenlper/gte-small; provide a compatible vector_service for another model")
    from ipfs_datasets_py.mcp_server.tools.vector_tools.vector_store_management import (
        search_vector_index,
    )
    result = await search_vector_index(
        index_name=collection,
        query=query,
        top_k=top_k,
        filters=filters or {},
    )
    if not isinstance(result, dict) or result.get("status") != "success" or result.get("error"):
        raise RuntimeError(str(result.get("error", "Vector search did not succeed")) if isinstance(result, dict) else "Invalid vector search result")
    # Normalize to the semantic_search response shape.
    results = result.get("results", [])
    return {
        "query": query,
        "model": model,
        "top_k": top_k,
        "collection": collection,
        "results": results,
        "total_found": len(results),
    }


async def similarity_search_from_parameters(
    *,
    vector_service: Any,
    embedding: List[float],
    top_k: int = 10,
    threshold: float = 0.5,
    collection: str = "default",
) -> Dict[str, Any]:
    """Find similar embeddings (currently a lightweight placeholder)."""
    results = [
        {
            "id": f"embedding_{i}",
            "similarity": 0.95 - (i * 0.05),
            "metadata": {
                "collection": collection,
                "dimension": len(embedding),
            },
        }
        for i in range(min(top_k, 5))
        if 0.95 - (i * 0.05) >= threshold
    ]

    return {
        "embedding_dimension": len(embedding),
        "top_k": top_k,
        "threshold": threshold,
        "collection": collection,
        "results": results,
        "total_found": len(results),
    }


async def faceted_search_from_parameters(
    *,
    vector_service: Any,
    query: str = "",
    facets: Optional[Dict[str, List[str]]] = None,
    aggregations: Optional[List[str]] = None,
    top_k: int = 20,
    collection: str = "default",
) -> Dict[str, Any]:
    """Perform a faceted search (currently a lightweight placeholder)."""
    facets = facets or {}
    aggregations = aggregations or []

    results = [
        {
            "id": f"doc_{i}",
            "text": f"Document {i} matching facets: {facets}",
            "score": 0.8 - (i * 0.1),
            "metadata": {
                "category": f"category_{i % 3}",
                "tags": [f"tag_{j}" for j in range(i % 2 + 1)],
                "date": f"2024-01-{i + 1:02d}",
            },
        }
        for i in range(min(top_k, 10))
    ]

    facet_counts = {
        "category": {"category_0": 4, "category_1": 3, "category_2": 3},
        "tags": {"tag_0": 8, "tag_1": 5},
    }

    return {
        "query": query,
        "facets": facets,
        "aggregations": aggregations,
        "top_k": top_k,
        "collection": collection,
        "results": results,
        "facet_counts": facet_counts,
        "total_found": len(results),
    }
