# Index Management Tools

MCP thin wrapper for vector/search index lifecycle management. Business logic lives in
`ipfs_datasets_py.indexing.index_manager_core`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `index_management_tools.py` | `create_index()`, `delete_index()`, `list_indices()`, `rebuild_index()`, `get_index_stats()` | Full index lifecycle: create, delete, list, rebuild, statistics |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.index_management_tools import (
    create_index, list_indices, rebuild_index, get_index_stats
)

# Create a new vector index
idx = await create_index(
    name="legal_corpus_v2",
    index_type="hnsw",          # "hnsw" | "flat" | "ivf" | "pq"
    dimensions=384,
    metric="cosine",
    backend="faiss"             # "faiss" | "qdrant" | "elasticsearch"
)

# List all indices
indices = await list_indices(backend="faiss")

# Rebuild after data changes
await rebuild_index(name="legal_corpus_v2", full_rebuild=True)

# Get stats
stats = await get_index_stats(name="legal_corpus_v2")
# Returns: {"vectors": 52000, "dimensions": 384, "size_mb": 79.4, "last_updated": "..."}
```

## Core Module

- `ipfs_datasets_py.indexing.index_manager_core` — all business logic

## Status

| Tool | Status |
|------|--------|
| `index_management_tools` | ✅ Production ready |
