"""
Storage Engine

Business logic for storage operations: enums, dataclasses, and MockStorageManager.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class StorageType(Enum):
    LOCAL = "local"
    IPFS = "ipfs"
    S3 = "s3"
    GOOGLE_CLOUD = "google_cloud"
    AZURE = "azure"
    MEMORY = "memory"


class CompressionType(Enum):
    NONE = "none"
    GZIP = "gzip"
    LZ4 = "lz4"
    BROTLI = "brotli"


@dataclass
class StorageItem:
    """Represents an item stored in the storage system."""
    id: str
    path: str
    size_bytes: int
    content_hash: str
    storage_type: StorageType
    compression: CompressionType
    metadata: Dict[str, Any]
    created_at: datetime
    accessed_at: datetime
    tags: List[str] = field(default_factory=list)


@dataclass
class Collection:
    """Represents a collection of stored items."""
    name: str
    description: str
    items: List[str]
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    storage_stats: Dict[str, Any] = field(default_factory=dict)


class MockStorageManager:
    """Mock storage manager for testing and development."""

    def __init__(self) -> None:
        self.items: Dict[str, StorageItem] = {}
        self.collections: Dict[str, Collection] = {}
        self.storage_stats: Dict[str, Any] = {
            "total_items": 0,
            "total_size_bytes": 0,
            "collections_count": 0,
            "storage_types": {t.value: 0 for t in StorageType},
            "compression_stats": {c.value: 0 for c in CompressionType},
        }
        self._create_default_collection()

    def _create_default_collection(self) -> None:
        default_collection = Collection(
            name="default",
            description="Default collection for items without specific collection",
            items=[],
            metadata={"auto_created": True},
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.collections["default"] = default_collection
        self.storage_stats["collections_count"] = 1

    def _generate_item_id(self, content: Union[str, bytes]) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()[:16]

    def store_item(
        self,
        content: Union[str, bytes, Dict[str, Any]],
        storage_type: StorageType = StorageType.MEMORY,
        compression: CompressionType = CompressionType.NONE,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        collection_name: str = "default",
    ) -> StorageItem:
        if isinstance(content, dict):
            content = json.dumps(content, indent=2)
        content_bytes = content.encode("utf-8") if isinstance(content, str) else content
        item_id = self._generate_item_id(content_bytes)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        compressed_size = len(content_bytes)
        if compression != CompressionType.NONE:
            compression_ratios = {
                CompressionType.GZIP: 0.6,
                CompressionType.LZ4: 0.7,
                CompressionType.BROTLI: 0.55,
            }
            compressed_size = int(len(content_bytes) * compression_ratios.get(compression, 0.6))
        now = datetime.now()
        item = StorageItem(
            id=item_id,
            path=f"/{storage_type.value}/{collection_name}/{item_id}",
            size_bytes=compressed_size,
            content_hash=content_hash,
            storage_type=storage_type,
            compression=compression,
            metadata=metadata or {},
            created_at=now,
            accessed_at=now,
            tags=tags or [],
        )
        self.items[item_id] = item
        if collection_name not in self.collections:
            self._create_collection(collection_name, f"Auto-created collection for {collection_name}")
        if item_id not in self.collections[collection_name].items:
            self.collections[collection_name].items.append(item_id)
            self.collections[collection_name].updated_at = now
        self.storage_stats["total_items"] += 1
        self.storage_stats["total_size_bytes"] += compressed_size
        self.storage_stats["storage_types"][storage_type.value] += 1
        self.storage_stats["compression_stats"][compression.value] += 1
        return item

    def retrieve_item(
        self, item_id: str, include_content: bool = False
    ) -> Optional[Dict[str, Any]]:
        if item_id not in self.items:
            return None
        item = self.items[item_id]
        item.accessed_at = datetime.now()
        result: Dict[str, Any] = {
            "id": item.id,
            "path": item.path,
            "size_bytes": item.size_bytes,
            "content_hash": item.content_hash,
            "storage_type": item.storage_type.value,
            "compression": item.compression.value,
            "metadata": item.metadata,
            "created_at": item.created_at.isoformat(),
            "accessed_at": item.accessed_at.isoformat(),
            "tags": item.tags,
        }
        if include_content:
            result["content"] = (
                f"Mock content for item {item_id} (stored in {item.storage_type.value})"
            )
        return result

    def list_items(
        self,
        collection_name: Optional[str] = None,
        storage_type: Optional[StorageType] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        items = list(self.items.values())
        if collection_name:
            if collection_name in self.collections:
                item_ids = set(self.collections[collection_name].items)
                items = [item for item in items if item.id in item_ids]
            else:
                return []
        if storage_type:
            items = [item for item in items if item.storage_type == storage_type]
        if tags:
            items = [item for item in items if any(tag in item.tags for tag in tags)]
        items.sort(key=lambda x: x.created_at, reverse=True)
        items = items[offset: offset + limit]
        return [
            {
                "id": item.id,
                "path": item.path,
                "size_bytes": item.size_bytes,
                "storage_type": item.storage_type.value,
                "compression": item.compression.value,
                "created_at": item.created_at.isoformat(),
                "tags": item.tags,
                "metadata": item.metadata,
            }
            for item in items
        ]

    def delete_item(self, item_id: str) -> bool:
        if item_id not in self.items:
            return False
        item = self.items[item_id]
        for collection in self.collections.values():
            if item_id in collection.items:
                collection.items.remove(item_id)
                collection.updated_at = datetime.now()
        self.storage_stats["total_items"] -= 1
        self.storage_stats["total_size_bytes"] -= item.size_bytes
        self.storage_stats["storage_types"][item.storage_type.value] -= 1
        self.storage_stats["compression_stats"][item.compression.value] -= 1
        del self.items[item_id]
        return True

    def _create_collection(self, name: str, description: str) -> Collection:
        collection = Collection(
            name=name,
            description=description,
            items=[],
            metadata={},
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        self.collections[name] = collection
        self.storage_stats["collections_count"] += 1
        return collection

    def create_collection(
        self,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if name in self.collections:
            raise ValueError(f"Collection '{name}' already exists")
        collection = self._create_collection(name, description)
        if metadata:
            collection.metadata.update(metadata)
        return {
            "name": collection.name,
            "description": collection.description,
            "metadata": collection.metadata,
            "created_at": collection.created_at.isoformat(),
            "items_count": len(collection.items),
        }

    def get_collection(self, name: str) -> Optional[Dict[str, Any]]:
        if name not in self.collections:
            return None
        collection = self.collections[name]
        total_size = sum(
            self.items[iid].size_bytes
            for iid in collection.items
            if iid in self.items
        )
        storage_breakdown: Dict[str, int] = {}
        for iid in collection.items:
            if iid in self.items:
                st = self.items[iid].storage_type.value
                storage_breakdown[st] = storage_breakdown.get(st, 0) + 1
        return {
            "name": collection.name,
            "description": collection.description,
            "metadata": collection.metadata,
            "items_count": len(collection.items),
            "total_size_bytes": total_size,
            "storage_breakdown": storage_breakdown,
            "created_at": collection.created_at.isoformat(),
            "updated_at": collection.updated_at.isoformat(),
        }

    def list_collections(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": c.name,
                "description": c.description,
                "items_count": len(c.items),
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in self.collections.values()
        ]

    def delete_collection(self, name: str, delete_items: bool = False) -> bool:
        if name not in self.collections:
            return False
        if name == "default":
            raise ValueError("Cannot delete default collection")
        collection = self.collections[name]
        if delete_items:
            for item_id in collection.items[:]:
                self.delete_item(item_id)
        else:
            for item_id in collection.items:
                if "default" not in self.collections:
                    self._create_default_collection()
                self.collections["default"].items.append(item_id)
        del self.collections[name]
        self.storage_stats["collections_count"] -= 1
        return True

    def get_storage_stats(self) -> Dict[str, Any]:
        avg_item_size = self.storage_stats["total_size_bytes"] / max(
            self.storage_stats["total_items"], 1
        )
        compression_usage = {
            comp_type: count / max(self.storage_stats["total_items"], 1)
            for comp_type, count in self.storage_stats["compression_stats"].items()
        }
        return {
            "basic_stats": self.storage_stats,
            "average_item_size_bytes": avg_item_size,
            "compression_usage_ratios": compression_usage,
            "largest_collection": (
                max(
                    self.collections.items(),
                    key=lambda x: len(x[1].items),
                    default=("none", Collection("", "", [], {}, datetime.now(), datetime.now())),
                )[0]
                if self.collections
                else "none"
            ),
            "storage_efficiency": {
                "total_items": self.storage_stats["total_items"],
                "total_size_mb": self.storage_stats["total_size_bytes"] / (1024 * 1024),
                "collections": len(self.collections),
            },
        }
