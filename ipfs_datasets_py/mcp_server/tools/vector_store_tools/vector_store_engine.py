"""
Vector Store Engine

Business logic (mock services) for vector store operations.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import anyio

logger = logging.getLogger(__name__)


class _AwaitableDict(dict):
    """Dict that can be awaited to return itself."""

    def __await__(self):
        async def _wrap():
            return self
        return _wrap().__await__()


class MockVectorStoreService:
    """Mock vector store service for development and testing."""

    def __init__(self) -> None:
        self.indexes: Dict[str, Any] = {}
        self.collections: Dict[str, List[Any]] = {}
        self.vectors: Dict[str, Any] = {}

    async def create_index(self, index_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        self.indexes[index_name] = {
            "config": config,
            "dimension": config.get("dimension", 768),
            "metric": config.get("metric", "cosine"),
            "index_type": config.get("index_type", "faiss"),
            "created_at": datetime.now().isoformat(),
            "vector_count": 0,
        }
        return {"status": "created", "index_name": index_name, "config": config}

    async def update_index(self, index_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        if index_name not in self.indexes:
            raise ValueError(f"Index '{index_name}' not found")
        self.indexes[index_name]["config"].update(config)
        return {"status": "updated", "index_name": index_name, "config": config}

    async def delete_index(self, index_name: str) -> Dict[str, Any]:
        if index_name not in self.indexes:
            raise ValueError(f"Index '{index_name}' not found")
        del self.indexes[index_name]
        return {"status": "deleted", "index_name": index_name}

    async def get_index_info(self, index_name: str) -> Dict[str, Any]:
        if index_name not in self.indexes:
            raise ValueError(f"Index '{index_name}' not found")
        return self.indexes[index_name]

    async def add_vectors(
        self, collection: str, vectors: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if collection not in self.collections:
            self.collections[collection] = []
        self.collections[collection].extend(vectors)
        status = "success" if collection in self.indexes else "added"
        return {"status": status, "collection": collection, "count": len(vectors)}

    async def search_vectors(
        self,
        collection: str,
        query_vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if collection not in self.collections:
            return {"results": [], "collection": collection}
        results = []
        for i, vector in enumerate(self.collections[collection][:top_k]):
            results.append({
                "id": vector.get("id", f"vec_{i}"),
                "score": 0.9 - (i * 0.1),
                "metadata": vector.get("metadata", {}),
                "vector": vector.get("vector", []),
            })
        return {"results": results, "collection": collection, "query_time_ms": 50}

    async def get_metadata(self, collection: str, vector_id: str) -> Dict[str, Any]:
        vectors = self.collections.get(collection, [])
        for vector in vectors:
            if vector.get("id") == vector_id:
                return {
                    "status": "success",
                    "vector_id": vector_id,
                    "metadata": vector.get("metadata", {}),
                }
        return {"status": "not_found", "vector_id": vector_id}

    async def update_metadata(
        self, collection: str, vector_id: str, metadata_updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        if collection not in self.collections:
            self.collections[collection] = []
        vectors = self.collections[collection]
        for vector in vectors:
            if vector.get("id") == vector_id:
                vector.setdefault("metadata", {}).update(metadata_updates)
                return {
                    "status": "updated",
                    "vector_id": vector_id,
                    "metadata": vector.get("metadata", {}),
                }
        vectors.append({"id": vector_id, "vector": [], "metadata": dict(metadata_updates)})
        return {"status": "updated", "vector_id": vector_id, "metadata": dict(metadata_updates)}

    async def get_stats(self, name: str) -> Dict[str, Any]:
        if name in self.indexes:
            index = self.indexes[name]
            stats = {
                "dimension": index.get("dimension"),
                "metric": index.get("metric"),
                "index_type": index.get("index_type"),
                "total_vectors": index.get("vector_count", 0),
            }
            return {"status": "success", "index_name": name, "stats": stats}
        if name in self.collections:
            collection = self.collections[name]
            dimension = None
            if collection:
                sample = collection[0].get("vector") if isinstance(collection[0], dict) else None
                if isinstance(sample, list):
                    dimension = len(sample)
            return {
                "status": "success",
                "collection": name,
                "stats": {"total_vectors": len(collection), "dimension": dimension},
            }
        return {"status": "success", "name": name, "stats": {"total_vectors": 0, "dimension": None}}

    async def delete_vectors(
        self,
        collection: str,
        ids: Optional[List[str]] = None,
        filter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if collection not in self.collections:
            return {"status": "not_found", "deleted_count": 0}
        vectors = self.collections[collection]
        original_count = len(vectors)
        if ids:
            vectors = [v for v in vectors if v.get("id") not in set(ids)]
        elif filter:
            def matches(vec: Dict[str, Any]) -> bool:
                metadata = vec.get("metadata", {})
                return all(metadata.get(k) == v for k, v in filter.items())
            vectors = [v for v in vectors if not matches(v)]
        deleted_count = original_count - len(vectors)
        self.collections[collection] = vectors
        status = "success" if deleted_count > 0 else "not_found"
        return {"status": status, "deleted_count": deleted_count}

    async def optimize_index(
        self, name: str, options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        await anyio.sleep(0)
        if name in self.indexes or name in self.collections:
            return {"status": "success", "index_name": name, "optimized": True,
                    "options": options or {}}
        return {"status": "success", "index_name": name, "optimized": False,
                "options": options or {}}
