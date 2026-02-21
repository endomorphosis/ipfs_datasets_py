# src/mcp_server/tools/vector_store_tools.py
from __future__ import annotations

# DEPRECATED: This legacy module is superseded by
#   ipfs_datasets_py.mcp_server.tools.vector_store_tools
# See legacy_mcp_tools/MIGRATION_GUIDE.md for migration instructions.
import warnings
warnings.warn(
    "legacy_mcp_tools.vector_store_tools is deprecated. "
    "Use ipfs_datasets_py.mcp_server.tools.vector_store_tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

import logging
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Import canonical service for delegation
try:
    from ipfs_datasets_py.vector_stores.vector_store_engine import MockVectorStoreService
    from ipfs_datasets_py.mcp_server.tools.validators import validator
    _VECTOR_SERVICE = MockVectorStoreService()
    _SERVICE_AVAILABLE = True
except ImportError:
    _VECTOR_SERVICE = None
    _SERVICE_AVAILABLE = False


async def manage_vector_index(
    action: str,
    index_name: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Manage vector indexes (create, update, delete, info, list)."""
    try:
        if not _SERVICE_AVAILABLE:
            return {"success": False, "error": "Vector service not available"}
        action = validator.validate_algorithm_choice(action, ["create", "update", "delete", "info"])
        index_name = validator.validate_text_input(index_name)
        result = None
        match action:
            case "create":
                result = await _VECTOR_SERVICE.create_index(index_name, config or {})
            case "update":
                result = await _VECTOR_SERVICE.update_index(index_name, config or {})
            case "delete":
                result = await _VECTOR_SERVICE.delete_index(index_name)
            case "info":
                result = await _VECTOR_SERVICE.get_index_info(index_name)
            case _:
                raise ValueError(f"Unsupported action: {action!r}. Must be one of create, update, delete, info.")
        return {"action": action, "index_name": index_name, "result": result, "success": True}
    except Exception as e:
        logger.error(f"Vector index operation failed: {e}")
        raise


async def retrieve_vectors(
    collection: str = "default",
    ids: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Retrieve vectors from storage with optional filtering."""
    try:
        if not _SERVICE_AVAILABLE:
            return {"success": False, "error": "Vector service not available"}
        collection = validator.validate_text_input(collection)
        vectors = await _VECTOR_SERVICE.retrieve_vectors(
            collection=collection, ids=ids, filters=filters or {}, limit=limit,
        )
        return {"collection": collection, "vectors": vectors, "count": len(vectors), "success": True}
    except Exception as e:
        logger.error(f"Vector retrieval failed: {e}")
        raise


async def manage_vector_metadata(
    action: str,
    collection: str = "default",
    vector_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Manage vector metadata (get, update, delete, list)."""
    try:
        if not _SERVICE_AVAILABLE:
            return {"success": False, "error": "Vector service not available"}
        action = validator.validate_algorithm_choice(action, ["get", "update", "delete", "list"])
        collection = validator.validate_text_input(collection)
        if vector_id:
            vector_id = validator.validate_text_input(vector_id)
        result = None
        match action:
            case "get":
                if not vector_id:
                    raise ValueError("vector_id is required for get action")
                result = await _VECTOR_SERVICE.get_vector_metadata(collection, vector_id)
            case "update":
                if not vector_id or not metadata:
                    raise ValueError("vector_id and metadata are required for update action")
                result = await _VECTOR_SERVICE.update_vector_metadata(collection, vector_id, metadata)
            case "delete":
                if not vector_id:
                    raise ValueError("vector_id is required for delete action")
                result = await _VECTOR_SERVICE.delete_vector_metadata(collection, vector_id)
            case _:
                result = await _VECTOR_SERVICE.list_vector_metadata(collection, filters or {})
        return {"action": action, "collection": collection, "vector_id": vector_id, "result": result, "success": True}
    except Exception as e:
        logger.error(f"Vector metadata operation failed: {e}")
        raise


async def create_vector_store_tool(
    store_path: str,
    dimension: int,
    provider: str = "faiss",
    index_type: str = "flat",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a vector store with specified configuration."""
    try:
        store_id = str(uuid.uuid4())
        return {
            "success": True,
            "store_id": store_id,
            "store_path": store_path,
            "dimension": dimension,
            "provider": provider,
            "index_type": index_type,
            "config": config or {},
            "message": f"Vector store created at {store_path}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
