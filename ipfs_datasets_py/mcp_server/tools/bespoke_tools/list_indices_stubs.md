# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/bespoke_tools/list_indices.py'

Files last updated: 1751509215.4179525

Stub file last updated: 2025-07-07 01:56:46

## list_indices

```python
async def list_indices(store_type: Optional[str] = None, include_stats: bool = False, namespace: Optional[str] = None) -> Dict[str, Any]:
    """
    List all vector indices across different vector stores.

Args:
    store_type: Filter by store type (faiss, qdrant, elasticsearch, chromadb)
    include_stats: Include statistics for each index
    namespace: Filter by namespace
    
Returns:
    Dict containing list of indices and their metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
