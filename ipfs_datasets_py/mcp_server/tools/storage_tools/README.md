# Storage Tools

MCP tools for multi-backend storage management: local filesystem, S3-compatible object
storage, and IPFS-backed storage. Business logic in `storage_engine.py`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `storage_engine.py` | `StorageEngine` / `MockStorageManager` | Business logic and mock manager for testing (not MCP-facing) |
| `storage_tools.py` | `store_data()`, `retrieve_data()`, `list_storage()`, `delete_data()`, `get_storage_stats()` | Unified storage CRUD across backends |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.storage_tools import (
    store_data, retrieve_data, list_storage
)

# Store data to a backend
result = await store_data(
    data=my_dataset,
    key="legal_corpus/v2/data.parquet",
    backend="s3",             # "s3" | "local" | "ipfs"
    metadata={"version": "2", "rows": 50000}
)

# Retrieve data
data = await retrieve_data(
    key="legal_corpus/v2/data.parquet",
    backend="s3"
)

# List stored objects
objects = await list_storage(
    prefix="legal_corpus/",
    backend="s3"
)
# Returns: {"objects": [{"key": "...", "size_bytes": 123456, "last_modified": "..."}]}

# Storage statistics
stats = await get_storage_stats(backend="s3")
# Returns: {"total_objects": 142, "total_bytes": 5_000_000_000, "backends": {...}}
```

## Core Module

- `storage_engine.MockStorageManager` — in-process mock for tests

## Status

| Tool | Status |
|------|--------|
| `storage_tools` | ✅ Production ready |
