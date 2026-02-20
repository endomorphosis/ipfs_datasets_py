"""
Storage management package for ipfs_datasets_py.

Provides storage operations, backends, and the MockStorageManager
used in development/testing.

Reusable by:
- MCP server tools (mcp_server/tools/storage_tools/)
- CLI commands
- Direct Python imports
"""
from .storage_engine import (
    StorageType,
    CompressionType,
    StorageItem,
    Collection,
    MockStorageManager,
)

__all__ = [
    "StorageType",
    "CompressionType",
    "StorageItem",
    "Collection",
    "MockStorageManager",
]
