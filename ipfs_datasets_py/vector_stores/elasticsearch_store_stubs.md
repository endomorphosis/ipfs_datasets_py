# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/vector_stores/elasticsearch_store.py'

Files last updated: 1751408933.7864563

Stub file last updated: 2025-07-07 02:02:26

## ElasticsearchVectorStore

```python
class ElasticsearchVectorStore(BaseVectorStore):
    """
    Elasticsearch vector store implementation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, config: VectorStoreConfig):
    """
    Initialize Elasticsearch vector store.

Args:
    config: Vector store configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchVectorStore

## _create_client

```python
def _create_client(self) -> AsyncElasticsearch:
    """
    Create Elasticsearch async client connection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchVectorStore

## _get_index_mapping

```python
def _get_index_mapping(self, dimension: int) -> Dict[str, Any]:
    """
    Get the mapping configuration for vector index.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchVectorStore

## _map_distance_metric

```python
def _map_distance_metric(self, distance_metric: str) -> str:
    """
    Map distance metric to Elasticsearch similarity function.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ElasticsearchVectorStore

## add_embeddings

```python
async def add_embeddings(self, embeddings: List[EmbeddingResult], collection_name: Optional[str] = None) -> List[str]:
    """
    Add embeddings to Elasticsearch index.

Args:
    embeddings: List of embedding results to add
    collection_name: Target index name
    
Returns:
    List of document IDs for the added embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## close

```python
async def close(self):
    """
    Close the Elasticsearch connection.
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## collection_exists

```python
async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
    """
    Check if an Elasticsearch index exists.

Args:
    collection_name: Name of the index to check
    
Returns:
    True if index exists
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## create_collection

```python
async def create_collection(self, collection_name: Optional[str] = None, dimension: Optional[int] = None, **kwargs) -> bool:
    """
    Create a new Elasticsearch index.

Args:
    collection_name: Name of the index to create
    dimension: Vector dimension
    **kwargs: Additional index parameters
    
Returns:
    True if index was created successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## delete_by_id

```python
async def delete_by_id(self, embedding_id: str, collection_name: Optional[str] = None) -> bool:
    """
    Delete an embedding by ID from Elasticsearch.

Args:
    embedding_id: ID of the embedding to delete
    collection_name: Index to delete from
    
Returns:
    True if embedding was deleted successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## delete_collection

```python
async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
    """
    Delete an Elasticsearch index.

Args:
    collection_name: Name of the index to delete
    
Returns:
    True if index was deleted successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## get_by_id

```python
async def get_by_id(self, embedding_id: str, collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
    """
    Retrieve an embedding by ID from Elasticsearch.

Args:
    embedding_id: ID of the embedding to retrieve
    collection_name: Index to search in
    
Returns:
    Embedding result if found, None otherwise
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## get_collection_info

```python
async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get information about an Elasticsearch index.

Args:
    collection_name: Name of the index
    
Returns:
    Dictionary with index information
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## list_collections

```python
async def list_collections(self) -> List[str]:
    """
    List all indices in Elasticsearch.

Returns:
    List of index names
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## search

```python
async def search(self, query_vector: List[float], top_k: int = 10, collection_name: Optional[str] = None, filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
    """
    Search for similar vectors in Elasticsearch.

Args:
    query_vector: Query vector to search for
    top_k: Number of results to return
    collection_name: Index to search in
    filter_dict: Optional metadata filters
    
Returns:
    List of search results
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore

## update_embedding

```python
async def update_embedding(self, embedding_id: str, embedding: EmbeddingResult, collection_name: Optional[str] = None) -> bool:
    """
    Update an existing embedding in Elasticsearch.

Args:
    embedding_id: ID of the embedding to update
    embedding: New embedding data
    collection_name: Index containing the embedding
    
Returns:
    True if embedding was updated successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** ElasticsearchVectorStore
