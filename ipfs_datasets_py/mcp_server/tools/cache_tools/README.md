# Cache Tools

MCP tools for cache management and performance monitoring. Thin wrappers around `CacheManager`.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `cache_tools.py` | `get_cache_stats()`, `clear_cache()`, `set_cache_entry()`, `get_cache_entry()`, `invalidate_pattern()` | Cache CRUD, stats, pattern invalidation |
| `enhanced_cache_tools.py` | `create_cache_namespace()`, `list_namespaces()`, `warm_cache()`, `get_hit_rate()`, … | Multi-namespace caching, cache warming, detailed metrics |

## Usage

```python
from ipfs_datasets_py.mcp_server.tools.cache_tools import get_cache_stats, clear_cache

# Get current cache performance
stats = await get_cache_stats(namespace="embeddings")
# Returns: {"hit_rate": 0.87, "entries": 1200, "memory_mb": 156, "evictions": 42}

# Clear a namespace
await clear_cache(namespace="embeddings")

# Cache a value
await set_cache_entry(
    key="dataset_hash_abc",
    value={"rows": 1000, "schema": [...]},
    namespace="metadata",
    ttl_seconds=3600
)

# Retrieve it
entry = await get_cache_entry(key="dataset_hash_abc", namespace="metadata")
```

## Core Module

- `ipfs_datasets_py.mcp_server.mcplusplus.result_cache` — `DiskCacheBackend`

## Status

| Tool | Status |
|------|--------|
| `cache_tools` | ✅ Production ready |
| `enhanced_cache_tools` | ✅ Production ready |
