# storage_tools.py

import anyio
import logging
import os
import json
import hashlib
from typing import Dict, Any, List, Optional, Union, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

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
    items: List[str]  # Item IDs
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    storage_stats: Dict[str, Any] = field(default_factory=dict)

class MockStorageManager:
    """Mock storage manager for testing and development."""
    
    def __init__(self):
        self.items: Dict[str, StorageItem] = {}
        self.collections: Dict[str, Collection] = {}
        self.storage_stats = {
            "total_items": 0,
            "total_size_bytes": 0,
            "collections_count": 0,
            "storage_types": {t.value: 0 for t in StorageType},
            "compression_stats": {c.value: 0 for c in CompressionType}
        }
        
        # Create default collection
        self._create_default_collection()
    
    def _create_default_collection(self):
        """Create default collection."""
        default_collection = Collection(
            name="default",
            description="Default collection for items without specific collection",
            items=[],
            metadata={"auto_created": True},
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.collections["default"] = default_collection
        self.storage_stats["collections_count"] = 1
    
    def _generate_item_id(self, content: Union[str, bytes]) -> str:
        """Generate unique ID for content."""
        if isinstance(content, str):
            content = content.encode('utf-8')
        return hashlib.sha256(content).hexdigest()[:16]
    
    def store_item(
        self,
        content: Union[str, bytes, Dict[str, Any]],
        storage_type: StorageType = StorageType.MEMORY,
        compression: CompressionType = CompressionType.NONE,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        collection_name: str = "default"
    ) -> StorageItem:
        """Store an item in the storage system."""
        
        # Serialize content if necessary
        if isinstance(content, dict):
            content = json.dumps(content, indent=2)
        
        if isinstance(content, str):
            content_bytes = content.encode('utf-8')
        else:
            content_bytes = content
        
        # Generate item ID and metadata
        item_id = self._generate_item_id(content_bytes)
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        
        # Mock compression
        compressed_size = len(content_bytes)
        if compression != CompressionType.NONE:
            # Simulate compression ratios
            compression_ratios = {
                CompressionType.GZIP: 0.6,
                CompressionType.LZ4: 0.7,
                CompressionType.BROTLI: 0.55
            }
            compressed_size = int(len(content_bytes) * compression_ratios.get(compression, 0.6))
        
        # Create storage item
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
            tags=tags or []
        )
        
        # Store item
        self.items[item_id] = item
        
        # Update collection
        if collection_name not in self.collections:
            self._create_collection(collection_name, f"Auto-created collection for {collection_name}")
        
        if item_id not in self.collections[collection_name].items:
            self.collections[collection_name].items.append(item_id)
            self.collections[collection_name].updated_at = now
        
        # Update stats
        self.storage_stats["total_items"] += 1
        self.storage_stats["total_size_bytes"] += compressed_size
        self.storage_stats["storage_types"][storage_type.value] += 1
        self.storage_stats["compression_stats"][compression.value] += 1
        
        return item
    
    def retrieve_item(self, item_id: str, include_content: bool = False) -> Optional[Dict[str, Any]]:
        """Retrieve an item by ID."""
        if item_id not in self.items:
            return None
        
        item = self.items[item_id]
        item.accessed_at = datetime.now()  # Update access time
        
        result = {
            "id": item.id,
            "path": item.path,
            "size_bytes": item.size_bytes,
            "content_hash": item.content_hash,
            "storage_type": item.storage_type.value,
            "compression": item.compression.value,
            "metadata": item.metadata,
            "created_at": item.created_at.isoformat(),
            "accessed_at": item.accessed_at.isoformat(),
            "tags": item.tags
        }
        
        if include_content:
            # Mock content retrieval
            result["content"] = f"Mock content for item {item_id} (stored in {item.storage_type.value})"
        
        return result
    
    def list_items(
        self,
        collection_name: Optional[str] = None,
        storage_type: Optional[StorageType] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List items with optional filtering."""
        items = list(self.items.values())
        
        # Apply filters
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
        
        # Sort by creation time (newest first)
        items.sort(key=lambda x: x.created_at, reverse=True)
        
        # Apply pagination
        items = items[offset:offset + limit]
        
        return [
            {
                "id": item.id,
                "path": item.path,
                "size_bytes": item.size_bytes,
                "storage_type": item.storage_type.value,
                "compression": item.compression.value,
                "created_at": item.created_at.isoformat(),
                "tags": item.tags,
                "metadata": item.metadata
            }
            for item in items
        ]
    
    def delete_item(self, item_id: str) -> bool:
        """Delete an item."""
        if item_id not in self.items:
            return False
        
        item = self.items[item_id]
        
        # Remove from collections
        for collection in self.collections.values():
            if item_id in collection.items:
                collection.items.remove(item_id)
                collection.updated_at = datetime.now()
        
        # Update stats
        self.storage_stats["total_items"] -= 1
        self.storage_stats["total_size_bytes"] -= item.size_bytes
        self.storage_stats["storage_types"][item.storage_type.value] -= 1
        self.storage_stats["compression_stats"][item.compression.value] -= 1
        
        # Delete item
        del self.items[item_id]
        return True
    
    def _create_collection(self, name: str, description: str) -> Collection:
        """Create a new collection."""
        collection = Collection(
            name=name,
            description=description,
            items=[],
            metadata={},
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        self.collections[name] = collection
        self.storage_stats["collections_count"] += 1
        return collection
    
    def create_collection(
        self,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a new collection."""
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
            "items_count": len(collection.items)
        }
    
    def get_collection(self, name: str) -> Optional[Dict[str, Any]]:
        """Get collection information."""
        if name not in self.collections:
            return None
        
        collection = self.collections[name]
        
        # Calculate storage stats
        total_size = sum(
            self.items[item_id].size_bytes
            for item_id in collection.items
            if item_id in self.items
        )
        
        storage_breakdown = {}
        for item_id in collection.items:
            if item_id in self.items:
                storage_type = self.items[item_id].storage_type.value
                storage_breakdown[storage_type] = storage_breakdown.get(storage_type, 0) + 1
        
        return {
            "name": collection.name,
            "description": collection.description,
            "metadata": collection.metadata,
            "items_count": len(collection.items),
            "total_size_bytes": total_size,
            "storage_breakdown": storage_breakdown,
            "created_at": collection.created_at.isoformat(),
            "updated_at": collection.updated_at.isoformat()
        }
    
    def list_collections(self) -> List[Dict[str, Any]]:
        """List all collections."""
        return [
            {
                "name": collection.name,
                "description": collection.description,
                "items_count": len(collection.items),
                "created_at": collection.created_at.isoformat(),
                "updated_at": collection.updated_at.isoformat()
            }
            for collection in self.collections.values()
        ]
    
    def delete_collection(self, name: str, delete_items: bool = False) -> bool:
        """Delete a collection."""
        if name not in self.collections:
            return False
        
        if name == "default":
            raise ValueError("Cannot delete default collection")
        
        collection = self.collections[name]
        
        if delete_items:
            # Delete all items in collection
            for item_id in collection.items[:]:  # Copy list to avoid modification during iteration
                self.delete_item(item_id)
        else:
            # Move items to default collection
            for item_id in collection.items:
                if "default" not in self.collections:
                    self._create_default_collection()
                self.collections["default"].items.append(item_id)
        
        del self.collections[name]
        self.storage_stats["collections_count"] -= 1
        return True
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get comprehensive storage statistics."""
        # Calculate additional stats
        avg_item_size = self.storage_stats["total_size_bytes"] / max(self.storage_stats["total_items"], 1)
        
        compression_usage = {
            comp_type: count / max(self.storage_stats["total_items"], 1)
            for comp_type, count in self.storage_stats["compression_stats"].items()
        }
        
        return {
            "basic_stats": self.storage_stats,
            "average_item_size_bytes": avg_item_size,
            "compression_usage_ratios": compression_usage,
            "largest_collection": max(
                self.collections.items(),
                key=lambda x: len(x[1].items),
                default=("none", Collection("", "", [], {}, datetime.now(), datetime.now()))
            )[0] if self.collections else "none",
            "storage_efficiency": {
                "total_items": self.storage_stats["total_items"],
                "total_size_mb": self.storage_stats["total_size_bytes"] / (1024 * 1024),
                "collections": len(self.collections)
            }
        }

# Global storage manager instance
_storage_manager = MockStorageManager()

async def store_data(
    data: Union[str, bytes, Dict[str, Any], List[Any]],
    storage_type: str = "memory",
    compression: str = "none",
    collection: str = "default",
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Store data in the storage system with specified configuration.
    
    Args:
        data: Data to store (text, bytes, JSON object, or list)
        storage_type: Type of storage backend to use
        compression: Compression algorithm to apply
        collection: Collection to store the data in
        metadata: Additional metadata to associate with the data
        tags: Tags for categorizing and filtering the data
    
    Returns:
        Dict containing storage operation results
    """
    try:
        logger.info(f"Storing data in {storage_type} storage with {compression} compression")
        
        # Validate inputs
        try:
            storage_enum = StorageType(storage_type)
        except ValueError:
            raise ValueError(f"Invalid storage type: {storage_type}. Valid types: {[t.value for t in StorageType]}")
        
        try:
            compression_enum = CompressionType(compression)
        except ValueError:
            raise ValueError(f"Invalid compression type: {compression}. Valid types: {[c.value for c in CompressionType]}")
        
        # Store the data
        item = _storage_manager.store_item(
            content=data,
            storage_type=storage_enum,
            compression=compression_enum,
            metadata=metadata,
            tags=tags,
            collection_name=collection
        )
        
        return {
            "stored": True,
            "item_id": item.id,
            "path": item.path,
            "size_bytes": item.size_bytes,
            "content_hash": item.content_hash,
            "storage_type": item.storage_type.value,
            "compression": item.compression.value,
            "collection": collection,
            "metadata": item.metadata,
            "tags": item.tags,
            "stored_at": item.created_at.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Data storage failed: {e}")
        raise

async def retrieve_data(
    item_ids: List[str],
    include_content: bool = False,
    format_type: str = "json"
) -> Dict[str, Any]:
    """
    Retrieve stored data by item IDs.
    
    Args:
        item_ids: List of item IDs to retrieve
        include_content: Whether to include actual content in response
        format_type: Format for returned data
    
    Returns:
        Dict containing retrieved data
    """
    try:
        logger.info(f"Retrieving {len(item_ids)} items with format: {format_type}")
        
        if not item_ids:
            raise ValueError("At least one item ID must be provided")
        
        results = []
        not_found = []
        
        for item_id in item_ids:
            item_data = _storage_manager.retrieve_item(item_id, include_content)
            if item_data:
                results.append(item_data)
            else:
                not_found.append(item_id)
        
        return {
            "retrieved_count": len(results),
            "not_found_count": len(not_found),
            "results": results,
            "not_found": not_found,
            "format": format_type,
            "include_content": include_content,
            "retrieved_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Data retrieval failed: {e}")
        raise

async def manage_collections(
    action: str,
    collection_name: Optional[str] = None,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    delete_items: bool = False
) -> Dict[str, Any]:
    """
    Manage storage collections (create, read, update, delete).
    
    Args:
        action: Action to perform (create, get, list, delete, update)
        collection_name: Name of the collection to manage
        description: Description for new collections
        metadata: Metadata for collections
        delete_items: Whether to delete items when deleting collection
    
    Returns:
        Dict containing collection management results
    """
    try:
        logger.info(f"Managing collections: action={action}, collection={collection_name}")
        
        if action == "create":
            if not collection_name:
                raise ValueError("collection_name required for create action")
            
            result = _storage_manager.create_collection(
                name=collection_name,
                description=description or "",
                metadata=metadata
            )
            
            return {
                "action": "create",
                "success": True,
                "collection": result
            }
        
        elif action == "get":
            if not collection_name:
                raise ValueError("collection_name required for get action")
            
            collection_data = _storage_manager.get_collection(collection_name)
            if not collection_data:
                return {
                    "action": "get",
                    "success": False,
                    "error": f"Collection '{collection_name}' not found"
                }
            
            return {
                "action": "get",
                "success": True,
                "collection": collection_data
            }
        
        elif action == "list":
            collections = _storage_manager.list_collections()
            return {
                "action": "list",
                "success": True,
                "collections": collections,
                "total_count": len(collections)
            }
        
        elif action == "delete":
            if not collection_name:
                raise ValueError("collection_name required for delete action")
            
            success = _storage_manager.delete_collection(collection_name, delete_items)
            
            return {
                "action": "delete",
                "success": success,
                "collection_name": collection_name,
                "items_deleted": delete_items
            }
        
        elif action == "stats":
            if collection_name:
                collection_data = _storage_manager.get_collection(collection_name)
                if not collection_data:
                    return {
                        "action": "stats",
                        "success": False,
                        "error": f"Collection '{collection_name}' not found"
                    }
                return {
                    "action": "stats",
                    "success": True,
                    "collection_stats": collection_data
                }
            else:
                stats = _storage_manager.get_storage_stats()
                return {
                    "action": "stats",
                    "success": True,
                    "global_stats": stats
                }
        
        else:
            return {
                "action": action,
                "success": False,
                "error": f"Unknown action: {action}"
            }
        
    except Exception as e:
        logger.error(f"Collection management failed: {e}")
        raise

async def query_storage(
    collection: Optional[str] = None,
    storage_type: Optional[str] = None,
    tags: Optional[List[str]] = None,
    size_range: Optional[Tuple[int, int]] = None,
    date_range: Optional[Tuple[str, str]] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Query and filter stored items based on various criteria.
    
    Args:
        collection: Filter by collection name
        storage_type: Filter by storage type
        tags: Filter by tags (items must have at least one tag)
        size_range: Filter by size range in bytes (min, max)
        date_range: Filter by creation date range (ISO format)
        limit: Maximum number of results to return
        offset: Number of results to skip
    
    Returns:
        Dict containing query results
    """
    try:
        logger.info(f"Querying storage with filters: collection={collection}, type={storage_type}")
        
        # Convert storage type to enum if provided
        storage_enum = None
        if storage_type:
            try:
                storage_enum = StorageType(storage_type)
            except ValueError:
                raise ValueError(f"Invalid storage type: {storage_type}")
        
        # Get initial results
        items = _storage_manager.list_items(
            collection_name=collection,
            storage_type=storage_enum,
            tags=tags,
            limit=limit * 2,  # Get more items for additional filtering
            offset=offset
        )
        
        # Apply additional filters
        filtered_items = items
        
        if size_range:
            min_size, max_size = size_range
            filtered_items = [
                item for item in filtered_items
                if min_size <= item["size_bytes"] <= max_size
            ]
        
        if date_range:
            start_date, end_date = date_range
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            
            filtered_items = [
                item for item in filtered_items
                if start_dt <= datetime.fromisoformat(item["created_at"]) <= end_dt
            ]
        
        # Apply final limit
        filtered_items = filtered_items[:limit]
        
        # Generate query statistics
        total_size = sum(item["size_bytes"] for item in filtered_items)
        storage_distribution = {}
        for item in filtered_items:
            storage_type = item["storage_type"]
            storage_distribution[storage_type] = storage_distribution.get(storage_type, 0) + 1
        
        return {
            "query_results": filtered_items,
            "total_found": len(filtered_items),
            "total_size_bytes": total_size,
            "storage_distribution": storage_distribution,
            "query_filters": {
                "collection": collection,
                "storage_type": storage_type,
                "tags": tags,
                "size_range": size_range,
                "date_range": date_range
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": len(items) == limit * 2  # Approximate
            },
            "queried_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Storage query failed: {e}")
        raise
