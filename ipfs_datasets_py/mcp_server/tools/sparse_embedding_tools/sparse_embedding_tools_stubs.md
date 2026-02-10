# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/sparse_embedding_tools/sparse_embedding_tools.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## MockSparseEmbeddingService

```python
class MockSparseEmbeddingService:
    """
    Mock sparse embedding service for testing and development.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SparseEmbedding

```python
@dataclass
class SparseEmbedding:
    """
    Represents a sparse embedding vector.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SparseModel

```python
class SparseModel(Enum):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockSparseEmbeddingService

## generate_sparse_embedding

```python
def generate_sparse_embedding(self, text: str, model: str = "splade", top_k: int = 100, normalize: bool = True) -> SparseEmbedding:
    """
    Generate sparse embedding for text.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockSparseEmbeddingService

## generate_sparse_embedding

```python
async def generate_sparse_embedding(text: str, model: str = "splade", top_k: int = 100, normalize: bool = True, return_dense: bool = False) -> Dict[str, Any]:
    """
    Generate sparse embeddings from text using various sparse models.

Args:
    text: Input text to generate embeddings for
    model: Sparse embedding model to use
    top_k: Number of top dimensions to keep
    normalize: Whether to normalize the embedding values
    return_dense: Whether to also return dense representation

Returns:
    Dict containing sparse embedding data
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## index_sparse_collection

```python
async def index_sparse_collection(collection_name: str, dataset: str, split: str = "train", column: str = "text", models: List[str] = None, batch_size: int = 100, index_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Index sparse embeddings for efficient retrieval.

Args:
    collection_name: Name for the indexed collection
    dataset: Dataset identifier to index
    split: Dataset split to use
    column: Text column to generate embeddings for
    models: List of sparse models to use
    batch_size: Batch size for processing
    index_config: Configuration for index creation

Returns:
    Dict containing indexing results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## index_sparse_embeddings

```python
def index_sparse_embeddings(self, collection_name: str, documents: List[Dict[str, Any]], model: str = "splade", index_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Index sparse embeddings for a collection.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockSparseEmbeddingService

## manage_sparse_models

```python
async def manage_sparse_models(action: str, model_name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Manage sparse embedding models and configurations.

Args:
    action: Management action (list, add, remove, configure)
    model_name: Name of specific model to manage
    config: Configuration for model operations

Returns:
    Dict containing management operation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## sparse_search

```python
def sparse_search(self, query: str, collection_name: str, model: str = "splade", top_k: int = 10, filters: Optional[Dict[str, Any]] = None, search_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Perform sparse vector search.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockSparseEmbeddingService

## sparse_search

```python
async def sparse_search(query: str, collection_name: str, model: str = "splade", top_k: int = 10, filters: Optional[Dict[str, Any]] = None, search_config: Optional[Dict[str, Any]] = None, explain_scores: bool = False) -> Dict[str, Any]:
    """
    Perform sparse vector search on indexed embeddings.

Args:
    query: Search query text
    collection_name: Collection to search in
    model: Sparse model to use for search
    top_k: Number of top results to return
    filters: Optional metadata filters
    search_config: Configuration for search behavior
    explain_scores: Whether to include score explanations

Returns:
    Dict containing search results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
