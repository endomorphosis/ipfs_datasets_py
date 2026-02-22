# ipfs_datasets_py/mcp_server/tools/vector_store_tools/enhanced_vector_store_tools.py
"""
Enhanced vector store tools — standalone async MCP functions.

Business logic (MockVectorStoreService) lives in
ipfs_datasets_py.vector_stores.vector_store_engine.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

# Import engine from core package (re-export for backward compat)
from ipfs_datasets_py.vector_stores.vector_store_engine import MockVectorStoreService, _AwaitableDict  # noqa: F401

logger = logging.getLogger(__name__)

_DEFAULT_VECTOR_SERVICE = MockVectorStoreService()


async def enhanced_vector_index(
    action: str,
    index_name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create, update, delete, or inspect vector indexes."""
    config = config or {}
    svc = _DEFAULT_VECTOR_SERVICE

    if action == "create":
        if index_name in svc.indexes:
            result: Dict[str, Any] = {"status": "exists", "index_name": index_name}
        else:
            svc.indexes[index_name] = {
                "config": config,
                "dimension": config.get("dimension", 768),
                "metric": config.get("metric", "cosine"),
                "index_type": config.get("index_type", "faiss"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "vector_count": 0,
            }
            result = {"status": "created", "index_name": index_name, "config": config}
    elif action == "update":
        if index_name not in svc.indexes:
            result = {"status": "not_found", "index_name": index_name}
        else:
            svc.indexes[index_name]["config"].update(config)
            result = {"status": "updated", "index_name": index_name, "config": config}
    elif action == "delete":
        if index_name in svc.indexes:
            del svc.indexes[index_name]
            result = {"status": "deleted", "index_name": index_name}
        else:
            result = {"status": "not_found", "index_name": index_name}
    elif action == "info":
        result = svc.indexes.get(index_name, {"status": "not_found", "index_name": index_name})
    elif action == "list":
        result = {"indexes": list(svc.indexes.keys()), "count": len(svc.indexes)}
    else:
        result = {"status": "invalid_action", "action": action}

    return _AwaitableDict({
        "action": action,
        "index_name": index_name,
        "result": result,
        "status": result.get("status", "success"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def enhanced_vector_search(
    collection: str,
    query_vector: List[float],
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
    score_threshold: Optional[float] = None,
    include_metadata: bool = True,
    include_vectors: bool = False,
    rerank: bool = False,
) -> Dict[str, Any]:
    """Perform advanced vector similarity search with optional filtering and reranking."""
    search_result = await _DEFAULT_VECTOR_SERVICE.search_vectors(collection=collection, query_vector=query_vector, top_k=top_k, filters=filters)
    results = search_result.get("results", [])
    if score_threshold is not None:
        results = [r for r in results if r.get("score", 0) >= score_threshold]
    processed: List[Dict[str, Any]] = []
    for r in results:
        item: Dict[str, Any] = {"id": r.get("id"), "score": r.get("score")}
        if include_metadata:
            item["metadata"] = r.get("metadata", {})
        if include_vectors:
            item["vector"] = r.get("vector", [])
        processed.append(item)
    if rerank and len(processed) > 1:
        processed.sort(key=lambda x: x["score"], reverse=True)
    return {
        "collection": collection,
        "query_dimension": len(query_vector),
        "results": processed,
        "total_results": len(processed),
        "top_k_requested": top_k,
        "score_threshold": score_threshold,
        "query_time_ms": search_result.get("query_time_ms", 0),
        "reranked": rerank,
        "status": "success",
    }


async def enhanced_vector_storage(
    action: str,
    collection: Optional[str] = None,
    vectors: Optional[List[Any]] = None,
    vector_ids: Optional[List[str]] = None,
    vector_id: Optional[str] = None,
    metadata_updates: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Store, update, or delete vectors in a collection."""
    collection = collection or "default"
    vectors = vectors or []
    vector_ids = vector_ids or []

    if action in ("add", "batch_add"):
        result: Dict[str, Any] = {"status": "success", "collection": collection, "count": len(vectors)}
    elif action == "update":
        result = {"status": "updated", "collection": collection, "count": len(vectors)}
    elif action == "delete":
        result = {"status": "deleted" if vector_id else "success", "collection": collection, "vector_id": vector_id, "ids": vector_ids}
    elif action in ("get", "list"):
        result = {"status": "success", "collection": collection, "vectors": []}
    elif action == "get_metadata":
        result = {"status": "not_found", "collection": collection, "vector_id": vector_id}
    else:
        result = {"status": "error", "error": f"Invalid action: {action}"}

    response: Dict[str, Any] = {
        "action": action,
        "collection": collection,
        "result": result,
        "status": result.get("status", "success"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if action == "delete" and vector_id:
        response["vector_id"] = vector_id
    if action in ("get", "list"):
        response["vectors"] = result.get("vectors", [])
    return _AwaitableDict(response)


# Backward-compatible class shims
class EnhancedVectorIndexTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Union[Dict[str, Any], str], **kwargs: Any) -> Dict[str, Any]:  # noqa: D102
        if not isinstance(parameters, dict):
            parameters = {"action": parameters, **kwargs}
        return await enhanced_vector_index(parameters.get("action", "list"), parameters.get("index_name"), parameters.get("config", {}))


class EnhancedVectorSearchTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D102
        return await enhanced_vector_search(
            parameters.get("collection") or parameters.get("index_name", ""),
            parameters["query_vector"],
            parameters.get("top_k", 10),
            parameters.get("filters"),
            parameters.get("score_threshold"),
            parameters.get("include_metadata", True),
            parameters.get("include_vectors", False),
            parameters.get("rerank", False),
        )


class EnhancedVectorStorageTool:
    """Backward-compatible shim."""
    async def execute(self, parameters: Union[Dict[str, Any], str], **kwargs: Any) -> Any:  # noqa: D102
        if not isinstance(parameters, dict):
            parameters = {"action": parameters, **kwargs}
        return await enhanced_vector_storage(
            parameters.get("action", "list"),
            parameters.get("collection"),
            parameters.get("vectors", []),
            parameters.get("vector_ids", []),
            parameters.get("vector_id"),
            parameters.get("metadata_updates"),
        )


# Module-level tool instances for registration (backward compat)
enhanced_vector_index_tool = EnhancedVectorIndexTool()
enhanced_vector_search_tool = EnhancedVectorSearchTool()
enhanced_vector_storage_tool = EnhancedVectorStorageTool()

__all__ = [
    "enhanced_vector_index",
    "enhanced_vector_search",
    "enhanced_vector_storage",
    "EnhancedVectorIndexTool",
    "EnhancedVectorSearchTool",
    "EnhancedVectorStorageTool",
    "MockVectorStoreService",
    "_AwaitableDict",
    "enhanced_vector_index_tool",
    "enhanced_vector_search_tool",
    "enhanced_vector_storage_tool",
]
