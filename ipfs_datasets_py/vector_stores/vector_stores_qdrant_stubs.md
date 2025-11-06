# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/vector_stores/qdrant_store.py'

## MockQuandrantClient

```python
class MockQuandrantClient:
```
## QdrantVectorStore

```python
class QdrantVectorStore(BaseVectorStore):
    """
    Qdrant vector store implementation.
    """
```
## __init__

```python
def __init__(self, config: VectorStoreConfig):
    """
    Initialize Qdrant vector store.

Args:
    config: Vector store configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** QdrantVectorStore

## _create_client

```python
def _create_client(self) -> QdrantClientType:
    """
    Create Qdrant client connection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QdrantVectorStore

## add_embeddings

```python
async def add_embeddings(self, embeddings: List[EmbeddingResult], collection_name: Optional[str] = None) -> List[str]:
    """
    Add embeddings to Qdrant collection.

Args:
    embeddings: List of embedding results to add
    collection_name: Target collection name
    
Returns:
    List of point IDs for the added embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## collection_exists

```python
async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
    """
    Check if a Qdrant collection exists.

Args:
    collection_name: Name of the collection to check
    
Returns:
    True if collection exists
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## create_collection

```python
async def create_collection(self, collection_name: Optional[str] = None, dimension: Optional[int] = None, **kwargs) -> bool:
    """
    Create a new Qdrant collection.

Args:
    collection_name: Name of the collection to create
    dimension: Vector dimension
    **kwargs: Additional collection parameters
    
Returns:
    True if collection was created successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## delete_by_id

```python
async def delete_by_id(self, embedding_id: str, collection_name: Optional[str] = None) -> bool:
    """
    Delete an embedding by ID from Qdrant.

Args:
    embedding_id: ID of the embedding to delete
    collection_name: Collection to delete from
    
Returns:
    True if embedding was deleted successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## delete_collection

```python
async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
    """
    Delete a Qdrant collection.

Args:
    collection_name: Name of the collection to delete
    
Returns:
    True if collection was deleted successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## get_by_id

```python
async def get_by_id(self, embedding_id: str, collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
    """
    Retrieve an embedding by ID from Qdrant.

Args:
    embedding_id: ID of the embedding to retrieve
    collection_name: Collection to search in
    
Returns:
    Embedding result if found, None otherwise
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## get_collection_info

```python
async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get information about a Qdrant collection.

Args:
    collection_name: Name of the collection
    
Returns:
    Dictionary with collection information
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## hash_chunk

```python
def hash_chunk(self, chunk: Dict[str, Any]) -> str:
    """
    Legacy method to hash a chunk.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QdrantVectorStore

## join_datasets

```python
async def join_datasets(self, dataset, knn_index, join_column):
    """
    Legacy method for joining datasets.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## list_collections

```python
async def list_collections(self) -> List[str]:
    """
    List all collections in Qdrant.

Returns:
    List of collection names
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## load_qdrant_iter

```python
async def load_qdrant_iter(self, dataset, knn_index, dataset_split = None, knn_index_split = None):
    """
    Legacy method for loading Qdrant data.
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## search

```python
async def search(self, query_vector: List[float], top_k: int = 10, collection_name: Optional[str] = None, filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
    """
    Search for similar vectors in Qdrant.

Args:
    query_vector: Query vector to search for
    top_k: Number of results to return
    collection_name: Collection to search in
    filter_dict: Optional metadata filters
    
Returns:
    List of search results
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore

## update_embedding

```python
async def update_embedding(self, embedding_id: str, embedding: EmbeddingResult, collection_name: Optional[str] = None) -> bool:
    """
    Update an existing embedding in Qdrant.

Args:
    embedding_id: ID of the embedding to update
    embedding: New embedding data
    collection_name: Collection containing the embedding
    
Returns:
    True if embedding was updated successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** QdrantVectorStore
