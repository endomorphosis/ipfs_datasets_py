# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/vector_tools/search_vector_index.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## search_vector_index

```python
async def search_vector_index(index_id: str, query_vector: List[float], top_k: int = 5, include_metadata: bool = True, include_distances: bool = True, filter_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Search a vector index for similar vectors.

Args:
    index_id: ID of the vector index to search
    query_vector: The query vector to search for
    top_k: Number of results to return
    include_metadata: Whether to include metadata in the results
    include_distances: Whether to include distance values in the results
    filter_metadata: Optional filter to apply to metadata

Returns:
    Dict containing search results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
