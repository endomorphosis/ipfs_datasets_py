# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/bespoke_tools/delete_index.py'

Files last updated: 1751509215.4179525

Stub file last updated: 2025-07-07 01:10:13

## delete_index

```python
async def delete_index(index_id: str, store_type: Optional[str] = None, confirm: bool = False, backup_before_delete: bool = True) -> Dict[str, Any]:
    """
    Delete a vector index from the specified vector store.

Args:
    index_id: Unique identifier of the index to delete
    store_type: Type of vector store (faiss, qdrant, elasticsearch, chromadb)
    confirm: Confirmation flag to prevent accidental deletion
    backup_before_delete: Whether to create a backup before deletion
    
Returns:
    Dict containing deletion results and metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
