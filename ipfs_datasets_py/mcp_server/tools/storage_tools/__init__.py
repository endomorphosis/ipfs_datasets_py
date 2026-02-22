"""
Storage Tools for IPFS Datasets MCP Server

Provides unified storage management across multiple backends: local
filesystem, S3-compatible object storage, and IPFS. Handles content
addressing, collection management, item retrieval, and storage statistics.

Core functions: store_data, retrieve_data,
list_stored_items, delete_stored_item, get_storage_stats.
"""
# storage_tools/__init__.py

from .storage_tools import (
    store_data,
    retrieve_data,
    manage_collections,
    query_storage,
    StorageType,
    CompressionType,
    StorageItem,
    Collection,
    MockStorageManager
)

__all__ = [
    "store_data",
    "retrieve_data",
    "manage_collections", 
    "query_storage",
    "StorageType",
    "CompressionType",
    "StorageItem",
    "Collection",
    "MockStorageManager"
]
