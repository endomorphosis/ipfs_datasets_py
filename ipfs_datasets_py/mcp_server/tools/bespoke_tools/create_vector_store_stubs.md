# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/bespoke_tools/create_vector_store.py'

Files last updated: 1751509215.4179525

Stub file last updated: 2025-07-07 01:56:46

## create_vector_store

```python
async def create_vector_store(store_name: str, store_type: str = "faiss", dimension: int = 768, metric: str = "cosine", namespace: Optional[str] = None, configuration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a new vector store with specified configuration.

Args:
    store_name: Name of the vector store to create
    store_type: Type of vector store (faiss, qdrant, elasticsearch, chromadb)
    dimension: Vector dimension for embeddings
    metric: Distance metric (cosine, euclidean, dot_product)
    namespace: Optional namespace for organization
    configuration: Additional store-specific configuration
    
Returns:
    Dict containing store creation results and metadata
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
