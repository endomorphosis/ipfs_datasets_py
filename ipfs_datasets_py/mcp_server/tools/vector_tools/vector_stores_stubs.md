# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/embedding_tools/vector_stores.py'

Files last updated: 1751408933.6964564

Stub file last updated: 2025-07-07 01:10:14

## manage_vector_store

```python
async def manage_vector_store(operation: str, store_type: str = "qdrant", **kwargs) -> Dict[str, Any]:
    """
    Tool for managing vector stores including creation, indexing, and querying.

Args:
    operation: Operation to perform (create, index, query, delete)
    store_type: Type of vector store (qdrant, elasticsearch, faiss)
    **kwargs: Additional parameters specific to the operation

Returns:
    Dict containing operation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## optimize_vector_store

```python
async def optimize_vector_store(store_type: str = "qdrant", optimization_type: str = "index") -> Dict[str, Any]:
    """
    Optimize vector store performance.

Args:
    store_type: Type of vector store to optimize
    optimization_type: Type of optimization (index, memory, disk)

Returns:
    Dict containing optimization results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
