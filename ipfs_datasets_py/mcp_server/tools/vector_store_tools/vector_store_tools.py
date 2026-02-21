# src/mcp_server/tools/vector_store_tools.py
"""
Vector store tools (thin MCP wrappers).

All vector-store logic lives in ipfs_datasets_py.vector_stores.vector_store_tools_api.
Each function below is a minimal async wrapper that unpacks MCP-style
parameters and delegates straight to the canonical implementation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ipfs_datasets_py.vector_stores.vector_store_tools_api import (
    add_embeddings_to_store_from_parameters,
    create_vector_store_from_parameters,
    delete_from_vector_store_from_parameters,
    get_vector_store_stats_from_parameters,
    manage_vector_index,
    manage_vector_metadata,
    optimize_vector_store_from_parameters,
    retrieve_vectors,
    search_vector_store_from_parameters,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thin standalone wrappers
# ---------------------------------------------------------------------------

async def vector_index(
    action: str,
    index_name: str,
    config: Optional[Dict[str, Any]] = None,
    vector_service: Any = None,
) -> Dict[str, Any]:
    """Manage vector indexes (create / update / delete / info).

    Args:
        action: One of "create", "update", "delete", "info".
        index_name: Name of the vector index.
        config: Optional configuration dict (dimension, metric, index_type).
        vector_service: Optional vector service instance.

    Returns:
        Dict with action result.
    """
    try:
        result = await manage_vector_index(
            vector_service=vector_service,
            action=action,
            index_name=index_name,
            config=config,
        )
        return {"action": action, "index_name": index_name, "result": result, "success": True}
    except Exception as exc:
        logger.error("vector_index failed: %s", exc)
        raise


async def vector_retrieval(
    collection: str = "default",
    ids: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 100,
    vector_service: Any = None,
) -> Dict[str, Any]:
    """Retrieve vectors from storage.

    Args:
        collection: Collection name.
        ids: Specific vector IDs to retrieve.
        filters: Metadata filters.
        limit: Maximum number of vectors.
        vector_service: Optional vector service instance.

    Returns:
        Dict with retrieved vectors.
    """
    try:
        return await retrieve_vectors(
            vector_service=vector_service,
            collection=collection,
            ids=ids,
            filters=filters,
            limit=limit,
        )
    except Exception as exc:
        logger.error("vector_retrieval failed: %s", exc)
        raise


async def vector_metadata(
    action: str,
    collection: str = "default",
    ids: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    vector_service: Any = None,
) -> Dict[str, Any]:
    """Manage vector metadata (get / update / delete).

    Args:
        action: One of "get", "update", "delete".
        collection: Collection name.
        ids: Vector IDs to operate on.
        metadata: Metadata to set (for update).
        vector_service: Optional vector service instance.

    Returns:
        Dict with metadata operation result.
    """
    try:
        return await manage_vector_metadata(
            vector_service=vector_service,
            action=action,
            collection=collection,
            ids=ids,
            metadata=metadata,
        )
    except Exception as exc:
        logger.error("vector_metadata failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Backward-compatible class aliases
# ---------------------------------------------------------------------------

class VectorIndexTool:  # noqa: E302
    """Thin compatibility shim — wraps vector_index()."""

    name = "manage_vector_index"

    def __init__(self, vector_service=None):
        self.vector_service = vector_service

    async def execute(self, action: str, index_name: str, config=None) -> Dict[str, Any]:
        return await vector_index(
            action=action, index_name=index_name, config=config,
            vector_service=self.vector_service,
        )


class VectorRetrievalTool:
    """Thin compatibility shim — wraps vector_retrieval()."""

    name = "retrieve_vectors"

    def __init__(self, vector_service=None):
        self.vector_service = vector_service

    async def execute(self, collection="default", ids=None, filters=None, limit=100) -> Dict[str, Any]:
        return await vector_retrieval(
            collection=collection, ids=ids, filters=filters, limit=limit,
            vector_service=self.vector_service,
        )


class VectorMetadataTool:
    """Thin compatibility shim — wraps vector_metadata()."""

    name = "manage_vector_metadata"

    def __init__(self, vector_service=None):
        self.vector_service = vector_service

    async def execute(self, action: str, collection="default", ids=None, metadata=None) -> Dict[str, Any]:
        return await vector_metadata(
            action=action, collection=collection, ids=ids, metadata=metadata,
            vector_service=self.vector_service,
        )
