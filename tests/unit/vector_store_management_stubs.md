# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/vector_tools/vector_store_management.py'

## _create_elasticsearch_index

```python
async def _create_elasticsearch_index(index_name: str, documents: List[Dict[str, Any]], vector_dim: int, distance_metric: str, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create Elasticsearch vector index
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _create_faiss_index

```python
async def _create_faiss_index(index_name: str, documents: List[Dict[str, Any]], vector_dim: int, distance_metric: str, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create FAISS vector index
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _create_qdrant_index

```python
async def _create_qdrant_index(index_name: str, documents: List[Dict[str, Any]], vector_dim: int, distance_metric: str, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create Qdrant vector index
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _search_faiss_index

```python
async def _search_faiss_index(index_name: str, query: str, top_k: int, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Search FAISS vector index
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## create_vector_index

```python
async def create_vector_index(index_name: str, documents: List[Dict[str, Any]], backend: str = "faiss", vector_dim: int = 384, distance_metric: str = "cosine", index_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Create a vector index for similarity search.

Args:
    index_name: Name of the index to create
    documents: List of documents with 'text' and optional 'metadata'
    backend: Vector store backend (faiss, qdrant, elasticsearch)
    vector_dim: Dimension of the vectors
    distance_metric: Distance metric (cosine, euclidean, dot_product)
    index_config: Backend-specific configuration
    
Returns:
    Dictionary with index creation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## delete_vector_index

```python
async def delete_vector_index(index_name: str, backend: str = "faiss", config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Delete a vector index.

Args:
    index_name: Name of the index to delete
    backend: Vector store backend
    config: Backend-specific configuration
    
Returns:
    Dictionary with deletion results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## list_vector_indexes

```python
async def list_vector_indexes(backend: str = "all") -> Dict[str, Any]:
    """
    List available vector indexes.

Args:
    backend: Backend to list indexes for (all, faiss, qdrant, elasticsearch)
    
Returns:
    Dictionary with list of available indexes
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## search_vector_index

```python
async def search_vector_index(index_name: str, query: str, backend: str = "faiss", top_k: int = 10, filters: Optional[Dict[str, Any]] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Search a vector index for similar documents.

Args:
    index_name: Name of the index to search
    query: Query text to search for
    backend: Vector store backend
    top_k: Number of top results to return
    filters: Optional filters for search
    config: Backend-specific configuration
    
Returns:
    Dictionary with search results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
