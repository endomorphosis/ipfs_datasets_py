# Bespoke Tools

Custom one-off utility tools for the MCP server that don't fit neatly into another category.

## Tools

| File | Function | Description |
|------|----------|-------------|
| `cache_stats.py` | `cache_stats(namespace?)` | Cache performance metrics: hit rate, memory usage, eviction counts |
| `system_health.py` | `system_health()` | System health: CPU, memory, disk, service status |
| `system_status.py` | `system_status()` | High-level system status summary |
| `create_vector_store.py` | `create_vector_store(...)` | Convenience wrapper to create a named vector store |
| `execute_workflow.py` | `execute_workflow(...)` | Convenience wrapper to run a workflow by name |
| `delete_index.py` | `delete_index(...)` | Delete a vector or search index |
| `list_indices.py` | `list_indices()` | List all available vector/search indices |

## Usage

### Cache Statistics

```python
from ipfs_datasets_py.mcp_server.tools.bespoke_tools import cache_stats

# All namespaces
stats = await cache_stats()

# Specific namespace
stats = await cache_stats(namespace="embeddings")
print(stats["hit_rate"], stats["memory_usage_mb"])
```

### System Health

```python
from ipfs_datasets_py.mcp_server.tools.bespoke_tools import system_health

health = await system_health()
print(health["status"])           # "healthy" | "degraded" | "critical"
print(health["cpu_percent"])
print(health["memory_percent"])
```

## Dependencies

- `psutil` — required for `system_health()` CPU/memory metrics
- All other tools use stdlib only
