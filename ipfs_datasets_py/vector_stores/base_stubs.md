# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/vector_stores/base.py'

Files last updated: 1751435172.0997643

Stub file last updated: 2025-07-07 02:02:26

## BaseVectorStore

```python
class BaseVectorStore(ABC):
    """
    Abstract base class for vector store implementations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorStoreConnectionError

```python
class VectorStoreConnectionError(VectorStoreError):
    """
    Exception raised when connection to vector store fails.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorStoreError

```python
class VectorStoreError(Exception):
    """
    Base exception for vector store operations.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorStoreOperationError

```python
class VectorStoreOperationError(VectorStoreError):
    """
    Exception raised when a vector store operation fails.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __aenter__

```python
async def __aenter__(self):
    """
    Async context manager entry.
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## __aexit__

```python
async def __aexit__(self, exc_type, exc_val, exc_tb):
    """
    Async context manager exit.
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## __enter__

```python
def __enter__(self):
    """
    Context manager entry.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseVectorStore

## __exit__

```python
def __exit__(self, exc_type, exc_val, exc_tb):
    """
    Context manager exit.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseVectorStore

## __init__

```python
def __init__(self, config: VectorStoreConfig):
    """
    Initialize the vector store with configuration.

Args:
    config: Vector store configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseVectorStore

## _create_client

```python
@abstractmethod
def _create_client(self):
    """
    Create the underlying client connection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseVectorStore

## add_embeddings

```python
@abstractmethod
async def add_embeddings(self, embeddings: List[EmbeddingResult], collection_name: Optional[str] = None) -> List[str]:
    """
    Add embeddings to the vector store.

Args:
    embeddings: List of embedding results to add
    collection_name: Target collection name
    
Returns:
    List of IDs for the added embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## batch_add_embeddings

```python
async def batch_add_embeddings(self, embeddings: List[EmbeddingResult], batch_size: int = 100, collection_name: Optional[str] = None) -> List[str]:
    """
    Add embeddings in batches.

Args:
    embeddings: List of embedding results to add
    batch_size: Size of each batch
    collection_name: Target collection name
    
Returns:
    List of IDs for all added embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## client

```python
@property
def client(self):
    """
    Get the underlying client connection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** BaseVectorStore

## close

```python
async def close(self):
    """
    Close the vector store connection.
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## collection_exists

```python
@abstractmethod
async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
    """
    Check if a collection exists.

Args:
    collection_name: Name of the collection to check
    
Returns:
    True if collection exists
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## create_collection

```python
@abstractmethod
async def create_collection(self, collection_name: Optional[str] = None, dimension: Optional[int] = None, **kwargs) -> bool:
    """
    Create a new collection/index.

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
* **Class:** BaseVectorStore

## delete_by_id

```python
@abstractmethod
async def delete_by_id(self, embedding_id: str, collection_name: Optional[str] = None) -> bool:
    """
    Delete an embedding by ID.

Args:
    embedding_id: ID of the embedding to delete
    collection_name: Collection to delete from
    
Returns:
    True if embedding was deleted successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## delete_collection

```python
@abstractmethod
async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
    """
    Delete a collection/index.

Args:
    collection_name: Name of the collection to delete
    
Returns:
    True if collection was deleted successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## get_by_id

```python
@abstractmethod
async def get_by_id(self, embedding_id: str, collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
    """
    Retrieve an embedding by ID.

Args:
    embedding_id: ID of the embedding to retrieve
    collection_name: Collection to search in
    
Returns:
    Embedding result if found, None otherwise
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## get_collection_info

```python
@abstractmethod
async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get information about a collection.

Args:
    collection_name: Name of the collection
    
Returns:
    Dictionary with collection information
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## list_collections

```python
@abstractmethod
async def list_collections(self) -> List[str]:
    """
    List all collections in the vector store.

Returns:
    List of collection names
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## search

```python
@abstractmethod
async def search(self, query_vector: List[float], top_k: int = 10, collection_name: Optional[str] = None, filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
    """
    Search for similar vectors.

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
* **Class:** BaseVectorStore

## similarity_search

```python
async def similarity_search(self, query_vector: List[float], top_k: int = 10, collection_name: Optional[str] = None, score_threshold: Optional[float] = None, filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
    """
    Search for similar vectors with optional score filtering.

Args:
    query_vector: Query vector to search for
    top_k: Number of results to return
    collection_name: Collection to search in
    score_threshold: Minimum similarity score threshold
    filter_dict: Optional metadata filters
    
Returns:
    List of search results above the score threshold
    """
```
* **Async:** True
* **Method:** True
* **Class:** BaseVectorStore

## update_embedding

```python
@abstractmethod
async def update_embedding(self, embedding_id: str, embedding: EmbeddingResult, collection_name: Optional[str] = None) -> bool:
    """
    Update an existing embedding.

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
* **Class:** BaseVectorStore
