# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/vector_stores/faiss_store.py'

Files last updated: 1751423974.7690384

Stub file last updated: 2025-07-07 02:02:26

## FAISSVectorStore

```python
class FAISSVectorStore(BaseVectorStore):
    """
    FAISS vector store implementation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## Index

```python
def Index(self):
    """
    Mock Index method.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockFaissIndex

## MockFaissIndex

```python
class MockFaissIndex:
    """
    Mock FAISS index for testing purposes.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, dimension: int):
```
* **Async:** False
* **Method:** True
* **Class:** MockFaissIndex

## __init__

```python
def __init__(self, config: VectorStoreConfig):
    """
    Initialize FAISS vector store.

Args:
    config: Vector store configuration
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _create_client

```python
def _create_client(self):
    """
    Create FAISS client (actually just return None since FAISS is local).
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _create_index

```python
def _create_index(self, dimension: int, index_type: str = "Flat") -> faiss.Index:
    """
    Create a FAISS index.

Args:
    dimension: Vector dimension
    index_type: Type of FAISS index

Returns:
    FAISS index object
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _ensure_collection_loaded

```python
def _ensure_collection_loaded(self, collection_name: str):
    """
    Ensure a collection is loaded into memory.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _get_index_file_path

```python
def _get_index_file_path(self, collection_name: str) -> str:
    """
    Get the file path for a FAISS index.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _get_metadata_file_path

```python
def _get_metadata_file_path(self, collection_name: str) -> str:
    """
    Get the file path for metadata storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _load_index

```python
def _load_index(self, collection_name: str) -> Optional[faiss.Index]:
    """
    Load a FAISS index from disk.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _load_metadata

```python
def _load_metadata(self, collection_name: str) -> Dict[str, Any]:
    """
    Load metadata from disk.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _save_index

```python
def _save_index(self, collection_name: str, index: faiss.Index):
    """
    Save a FAISS index to disk.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## _save_metadata

```python
def _save_metadata(self, collection_name: str, metadata: Dict[str, Any]):
    """
    Save metadata to disk.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FAISSVectorStore

## add

```python
def add(self, vectors):
    """
    Mock add method.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockFaissIndex

## add_embeddings

```python
async def add_embeddings(self, embeddings: List[EmbeddingResult], collection_name: Optional[str] = None) -> List[str]:
    """
    Add embeddings to FAISS collection.

Args:
    embeddings: List of embedding results to add
    collection_name: Target collection name
    
Returns:
    List of IDs for the added embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## autofaiss_chunks_legacy

```python
async def autofaiss_chunks_legacy(self, *args, **kwargs):
    """
    Legacy autofaiss chunks method.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## autofaiss_shards_legacy

```python
async def autofaiss_shards_legacy(self, *args, **kwargs):
    """
    Legacy autofaiss shards method.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## collection_exists

```python
async def collection_exists(self, collection_name: Optional[str] = None) -> bool:
    """
    Check if a FAISS collection exists.

Args:
    collection_name: Name of the collection to check
    
Returns:
    True if collection exists
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## create_collection

```python
async def create_collection(self, collection_name: Optional[str] = None, dimension: Optional[int] = None, **kwargs) -> bool:
    """
    Create a new FAISS collection.

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
* **Class:** FAISSVectorStore

## delete_by_id

```python
async def delete_by_id(self, embedding_id: str, collection_name: Optional[str] = None) -> bool:
    """
    Delete an embedding by ID from FAISS.

Note: FAISS doesn't support efficient deletion. This marks the item as deleted
in metadata but doesn't remove it from the index.

Args:
    embedding_id: ID of the embedding to delete
    collection_name: Collection to delete from
    
Returns:
    True if embedding was marked as deleted
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## delete_collection

```python
async def delete_collection(self, collection_name: Optional[str] = None) -> bool:
    """
    Delete a FAISS collection.

Args:
    collection_name: Name of the collection to delete
    
Returns:
    True if collection was deleted successfully
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## get_by_id

```python
async def get_by_id(self, embedding_id: str, collection_name: Optional[str] = None) -> Optional[EmbeddingResult]:
    """
    Retrieve an embedding by ID from FAISS.

Args:
    embedding_id: ID of the embedding to retrieve
    collection_name: Collection to search in
    
Returns:
    Embedding result if found, None otherwise
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## get_collection_info

```python
async def get_collection_info(self, collection_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get information about a FAISS collection.

Args:
    collection_name: Name of the collection
    
Returns:
    Dictionary with collection information
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## kmeans_cluster_split_dataset_legacy

```python
async def kmeans_cluster_split_dataset_legacy(self, *args, **kwargs):
    """
    Legacy kmeans cluster split dataset method.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## list_collections

```python
async def list_collections(self) -> List[str]:
    """
    List all FAISS collections.

Returns:
    List of collection names
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## read_index

```python
def read_index(self, path):
    """
    Mock read index method.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockFaissIndex

## search

```python
def search(self, query_vector, top_k):
    """
    Mock search method.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockFaissIndex

## search

```python
async def search(self, query_vector: List[float], top_k: int = 10, collection_name: Optional[str] = None, filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
    """
    Search for similar vectors in FAISS.

Args:
    query_vector: Query vector to search for
    top_k: Number of results to return
    collection_name: Collection to search in
    filter_dict: Optional metadata filters (applied post-search)
    
Returns:
    List of search results
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## search_centroids_legacy

```python
async def search_centroids_legacy(self, *args, **kwargs):
    """
    Legacy search centroids method.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## search_chunks_legacy

```python
async def search_chunks_legacy(self, dataset, split, src_path, model, cids, query, endpoint = None, n = 64):
    """
    Legacy search chunks method.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## search_shards_legacy

```python
async def search_shards_legacy(self, *args, **kwargs):
    """
    Legacy search shards method.
    """
```
* **Async:** True
* **Method:** True
* **Class:** FAISSVectorStore

## update_embedding

```python
async def update_embedding(self, embedding_id: str, embedding: EmbeddingResult, collection_name: Optional[str] = None) -> bool:
    """
    Update an existing embedding in FAISS.

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
* **Class:** FAISSVectorStore

## write_index

```python
def write_index(self, path):
    """
    Mock write index method.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockFaissIndex
