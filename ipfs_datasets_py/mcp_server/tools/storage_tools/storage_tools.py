# storage_tools.py (thin wrapper)

import anyio
import logging
from typing import Dict, Any, List, Optional, Union, Tuple
from datetime import datetime

from .storage_engine import (  # noqa: F401
    StorageType,
    CompressionType,
    StorageItem,
    Collection,
    MockStorageManager,
)

logger = logging.getLogger(__name__)

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
