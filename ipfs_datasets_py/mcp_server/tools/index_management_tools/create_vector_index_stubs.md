# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/vector_tools/create_vector_index.py'

Files last updated: 1751597475.9319913

Stub file last updated: 2025-07-07 01:10:14

## create_vector_index

```python
async def create_vector_index(vectors: List[List[float]], dimension: Optional[int] = None, metric: str = "cosine", metadata: Optional[List[Dict[str, Any]]] = None, index_id: Optional[str] = None, index_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Create a vector index for similarity search.

Args:
    vectors: List of vectors to index
    dimension: Dimension of the vectors (inferred if not provided)
    metric: Distance metric to use ('cosine', 'l2', 'ip', etc.)
    metadata: Optional metadata for each vector
    index_id: Optional ID for the index (generated if not provided)
    index_name: Optional name for the index

Returns:
    Dict containing information about the created index
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
