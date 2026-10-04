# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/ipld/vector_store.py'

Files last updated: 1748635923.4413795

Stub file last updated: 2025-07-07 02:15:34

## IPLDVectorStore

```python
class IPLDVectorStore:
    """
    IPLD-based vector storage for embeddings.

This class provides a vector store implementation that uses IPLD for
content-addressed storage of embedding vectors. It supports efficient
nearest-neighbor search for similarity queries and can be serialized
to/from CAR files for portability.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SearchResult

```python
@dataclass
class SearchResult:
    """
    Represents a search result from a vector store.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, dimension: int = 768, metric: str = "cosine", storage: Optional[IPLDStorage] = None):
    """
    Initialize vector store with dimension and similarity metric.

Args:
    dimension: int - Dimensionality of vectors
    metric: str - Distance metric ('cosine', 'l2', 'ip')
    storage: Optional[IPLDStorage] - IPLD storage to use
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## __len__

```python
def __len__(self) -> int:
    """
    Get the number of vectors in the store.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## __str__

```python
def __str__(self) -> str:
    """
    Get a string representation of the vector store.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## _init_index

```python
def _init_index(self):
    """
    Initialize the vector index based on the metric.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## _numpy_search

```python
def _numpy_search(self, query_vector: np.ndarray, top_k: int, filter_fn: Optional[callable]) -> List[SearchResult]:
    """
    Perform search using numpy (fallback when FAISS is not available).

Args:
    query_vector: np.ndarray - Query vector
    top_k: int - Number of results to return
    filter_fn: Optional[callable] - Function to filter results

Returns:
    List[SearchResult] - Ranked search results
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## _update_root_cid

```python
def _update_root_cid(self):
    """
    Update the root CID of the vector store.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## add_vectors

```python
def add_vectors(self, vectors: List[np.ndarray], metadata: Optional[List[Dict[str, Any]]] = None) -> List[VectorID]:
    """
    Store vectors in IPLD format.

Args:
    vectors: List[np.ndarray] - List of vectors to store
    metadata: List[dict] - Optional metadata for each vector

Returns:
    List[str] - List of vector IDs (CIDs)
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## delete_vectors

```python
def delete_vectors(self, vector_ids: List[VectorID]) -> bool:
    """
    Delete vectors from the store.

Args:
    vector_ids: List[str] - Vector IDs to delete

Returns:
    bool - Success status
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## export_to_car

```python
def export_to_car(self, output_path: str) -> VectorID:
    """
    Export vector index to CAR file.

Args:
    output_path: str - Path to output CAR file

Returns:
    str - Root CID of the exported index
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## export_to_ipld

```python
def export_to_ipld(self) -> Tuple[VectorID, Dict[VectorID, bytes]]:
    """
    Export vector index as IPLD structure.

Returns:
    tuple: (root_cid, {cid: block_data}) - Root CID and blocks
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## from_car

```python
@classmethod
def from_car(cls, car_path: str, storage: Optional[IPLDStorage] = None) -> "IPLDVectorStore":
    """
    Load vector store from CAR file.

Args:
    car_path: str - Path to CAR file
    storage: Optional[IPLDStorage] - Storage to use

Returns:
    IPLDVectorStore - Loaded vector store
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## from_cid

```python
@classmethod
def from_cid(cls, cid: VectorID, storage: Optional[IPLDStorage] = None) -> "IPLDVectorStore":
    """
    Load vector store from IPFS by CID.

Args:
    cid: str - Root CID of the vector store
    storage: Optional[IPLDStorage] - Storage to use

Returns:
    IPLDVectorStore - Loaded vector store
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## get_metadata

```python
def get_metadata(self, vector_id: VectorID) -> Optional[Dict[str, Any]]:
    """
    Get metadata for a vector.

Args:
    vector_id: str - Vector ID

Returns:
    Optional[Dict[str, Any]] - The metadata if found, None otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## get_metrics

```python
def get_metrics(self) -> Dict[str, Any]:
    """
    Get vector store metrics.

Returns:
    Dict[str, Any] - Dictionary of metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## get_vector

```python
def get_vector(self, vector_id: VectorID) -> Optional[np.ndarray]:
    """
    Get a vector by its ID.

Args:
    vector_id: str - Vector ID

Returns:
    Optional[np.ndarray] - The vector if found, None otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## search

```python
def search(self, query_vector: np.ndarray, top_k: int = 10, filter_fn: Optional[callable] = None) -> List[SearchResult]:
    """
    Perform vector similarity search.

Args:
    query_vector: np.ndarray - Query vector
    top_k: int - Number of results to return
    filter_fn: Optional[callable] - Function to filter results

Returns:
    List[SearchResult] - Ranked search results
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** SearchResult

## update_metadata

```python
def update_metadata(self, vector_id: VectorID, metadata: Dict[str, Any]) -> bool:
    """
    Update metadata for a vector.

Args:
    vector_id: str - Vector ID
    metadata: Dict[str, Any] - New metadata

Returns:
    bool - Success status
    """
```
* **Async:** False
* **Method:** True
* **Class:** IPLDVectorStore
