# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/federated_search.py'

## AggregatedSearchResults

```python
@dataclass
class AggregatedSearchResults:
    """
    Represents search results aggregated from multiple nodes.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DistributedSearchIndex

```python
class DistributedSearchIndex:
    """
    Utility for creating and managing distributed search indices.

This class assists with creating and managing search indices for sharded
datasets distributed across IPFS nodes, with support for vector similarity,
keyword, and hybrid searches.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## FederatedSearch

```python
class FederatedSearch:
    """
    Main class for federated search across distributed dataset fragments.

This class provides methods for searching sharded datasets across multiple
IPFS nodes, with support for vector similarity, keyword, and hybrid searches.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## INetStream

```python
class INetStream:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RankingStrategy

```python
class RankingStrategy(Enum):
    """
    Strategies for ranking and aggregating results from multiple nodes.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SearchQuery

```python
@dataclass
class SearchQuery:
    """
    Represents a search query to be executed across the network.
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
    Represents a single search result.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SearchType

```python
class SearchType(Enum):
    """
    Types of search supported by the federated search system.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, node: Any, storage_dir: Optional[str] = None, max_concurrent_requests: int = 10, default_timeout_ms: int = 5000, use_cache: bool = True, cache_ttl_seconds: int = 300, max_cache_size: int = 100, ranking_strategy: RankingStrategy = RankingStrategy.SCORE):
    """
    Initialize the federated search engine.

Args:
    node: The LibP2P node for network communication
    storage_dir: Directory for storing search indices and caches
    max_concurrent_requests: Maximum concurrent search requests
    default_timeout_ms: Default timeout for search requests in milliseconds
    use_cache: Whether to use result caching
    cache_ttl_seconds: Time-to-live for cached results in seconds
    max_cache_size: Maximum number of cached queries
    ranking_strategy: Strategy for ranking and aggregating results
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## __init__

```python
def __init__(self, dataset_id: str, base_dir: str, vector_dimensions: Optional[int] = None, distance_metric: str = "cosine", enable_faiss: bool = True):
    """
    Initialize a distributed search index.

Args:
    dataset_id: ID of the dataset for this index
    base_dir: Base directory for index storage
    vector_dimensions: Dimensions of vectors (for vector search)
    distance_metric: Distance metric for vector search
    enable_faiss: Whether to use FAISS for vector search if available
    """
```
* **Async:** False
* **Method:** True
* **Class:** DistributedSearchIndex

## _check_cache

```python
def _check_cache(self, query_hash: str) -> Optional[AggregatedSearchResults]:
    """
    Check if results for this query are in the cache.

Args:
    query_hash: Hash of the query

Returns:
    Optional[AggregatedSearchResults]: Cached results or None
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## _filter_search_shard

```python
async def _filter_search_shard(self, shard: ShardMetadata, shard_path: str, query: SearchQuery) -> List[SearchResult]:
    """
    Perform filter-based search on a shard.

Args:
    shard: Metadata for the shard
    shard_path: Path to the shard file
    query: The search query

Returns:
    List[SearchResult]: Search results from this shard
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## _generate_query_hash

```python
def _generate_query_hash(self, query: SearchQuery) -> str:
    """
    Generate a hash key for the query for caching purposes.

Args:
    query: The search query

Returns:
    str: Hash of the query
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## _handle_federated_search

```python
async def _handle_federated_search(self, stream: "INetStream"):
    """
    Handle incoming federated search requests.

Args:
    stream: The network stream
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## _hybrid_search_shard

```python
async def _hybrid_search_shard(self, shard: ShardMetadata, shard_path: str, query: SearchQuery) -> List[SearchResult]:
    """
    Perform hybrid search (vector + keyword) on a shard.

Args:
    shard: Metadata for the shard
    shard_path: Path to the shard file
    query: The search query

Returns:
    List[SearchResult]: Search results from this shard
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## _init_vector_index

```python
def _init_vector_index(self):
    """
    Initialize the FAISS vector index.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DistributedSearchIndex

## _keyword_search_shard

```python
async def _keyword_search_shard(self, shard: ShardMetadata, shard_path: str, query: SearchQuery) -> List[SearchResult]:
    """
    Perform keyword search on a shard.

Args:
    shard: Metadata for the shard
    shard_path: Path to the shard file
    query: The search query

Returns:
    List[SearchResult]: Search results from this shard
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## _query_node

```python
async def _query_node(self, node_id: str, request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send a search request to a specific node.

Args:
    node_id: ID of the node to query
    request: The search request

Returns:
    Dict[str, Any]: Response from the node
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## _rank_results

```python
def _rank_results(self, results: List[SearchResult], top_k: int, strategy: RankingStrategy) -> List[SearchResult]:
    """
    Rank and limit the search results.

Args:
    results: The search results to rank
    top_k: Maximum number of results to return
    strategy: Ranking strategy to use

Returns:
    List[SearchResult]: Ranked and limited results
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## _search_local_shards

```python
async def _search_local_shards(self, query: SearchQuery) -> List[SearchResult]:
    """
    Search locally available shards for the query.

Args:
    query: The search query

Returns:
    List[SearchResult]: Search results from local shards
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## _search_remote_nodes

```python
async def _search_remote_nodes(self, query: SearchQuery, node_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Search for data on remote nodes.

Args:
    query: The search query
    node_ids: IDs of nodes to search

Returns:
    List[Dict[str, Any]]: Results from each node
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## _setup_protocol_handlers

```python
def _setup_protocol_handlers(self):
    """
    Set up protocol handlers for federated search.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## _update_cache

```python
def _update_cache(self, query_hash: str, results: AggregatedSearchResults):
    """
    Update the cache with new results.

Args:
    query_hash: Hash of the query
    results: The search results
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## _vector_search_shard

```python
async def _vector_search_shard(self, shard: ShardMetadata, shard_path: str, query: SearchQuery) -> List[SearchResult]:
    """
    Perform vector search on a shard.

Args:
    shard: Metadata for the shard
    shard_path: Path to the shard file
    query: The search query

Returns:
    List[SearchResult]: Search results from this shard
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## build_for_dataset

```python
@classmethod
async def build_for_dataset(cls, dataset_id: str, shard_manager: Any, base_dir: str, vector_dimensions: Optional[int] = None, distance_metric: str = "cosine", vector_field: str = "vector", text_fields: Optional[List[str]] = None, include_all_text_fields: bool = True) -> "DistributedSearchIndex":
    """
    Build search indices for an entire dataset.

Args:
    dataset_id: ID of the dataset
    shard_manager: Shard manager instance
    base_dir: Base directory for index storage
    vector_dimensions: Dimensions of vectors
    distance_metric: Distance metric for vector search
    vector_field: Field containing vectors
    text_fields: Fields to index for text search
    include_all_text_fields: Whether to index all text fields

Returns:
    DistributedSearchIndex: The created index
    """
```
* **Async:** True
* **Method:** True
* **Class:** DistributedSearchIndex

## build_indices_for_shard

```python
async def build_indices_for_shard(self, shard_path: str, shard_id: str, shard_format: str = "parquet", vector_field: str = "vector", text_fields: Optional[List[str]] = None, include_all_text_fields: bool = True) -> Dict[str, Any]:
    """
    Build search indices for a shard.

Args:
    shard_path: Path to the shard file
    shard_id: ID of the shard
    shard_format: Format of the shard
    vector_field: Field containing vectors
    text_fields: Fields to index for text search
    include_all_text_fields: Whether to index all text fields

Returns:
    Dict[str, Any]: Index building results
    """
```
* **Async:** True
* **Method:** True
* **Class:** DistributedSearchIndex

## clear_cache

```python
def clear_cache(self):
    """
    Clear the search result cache.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## filter_search

```python
async def filter_search(self, dataset_id: str, filters: List[Dict[str, Any]], top_k: int = 10, timeout_ms: int = 5000, include_metadata: bool = True) -> AggregatedSearchResults:
    """
    Perform a federated filter search.

Args:
    dataset_id: ID of the dataset to search
    filters: List of filters to apply
    top_k: Maximum number of results to return
    timeout_ms: Timeout in milliseconds
    include_metadata: Whether to include metadata in results

Returns:
    AggregatedSearchResults: Search results
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## get_statistics

```python
def get_statistics(self) -> Dict[str, Any]:
    """
    Get statistics about search operations.

Returns:
    Dict[str, Any]: Search statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## hybrid_search

```python
async def hybrid_search(self, dataset_id: str, query_text: str, query_vector: List[float], fields: Optional[List[str]] = None, top_k: int = 10, vector_weight: float = 0.5, text_weight: float = 0.5, timeout_ms: int = 5000, include_metadata: bool = True) -> AggregatedSearchResults:
    """
    Perform a federated hybrid search (vector + keyword).

Args:
    dataset_id: ID of the dataset to search
    query_text: Text to search for
    query_vector: Vector to search for
    fields: Fields to search in (all text fields if None)
    top_k: Maximum number of results to return
    vector_weight: Weight for vector similarity (0.0 to 1.0)
    text_weight: Weight for text similarity (0.0 to 1.0)
    timeout_ms: Timeout in milliseconds
    include_metadata: Whether to include metadata in results

Returns:
    AggregatedSearchResults: Search results
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## keyword_search

```python
async def keyword_search(self, dataset_id: str, query_text: str, fields: Optional[List[str]] = None, top_k: int = 10, operator: str = "and", timeout_ms: int = 5000, include_metadata: bool = True) -> AggregatedSearchResults:
    """
    Perform a federated keyword search.

Args:
    dataset_id: ID of the dataset to search
    query_text: Text to search for
    fields: Fields to search in (all text fields if None)
    top_k: Maximum number of results to return
    operator: Logical operator for term matching (and, or)
    timeout_ms: Timeout in milliseconds
    include_metadata: Whether to include metadata in results

Returns:
    AggregatedSearchResults: Search results
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## reset_statistics

```python
def reset_statistics(self):
    """
    Reset all search statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** FederatedSearch

## save_indices

```python
def save_indices(self):
    """
    Save all indices to disk.
    """
```
* **Async:** False
* **Method:** True
* **Class:** DistributedSearchIndex

## search

```python
async def search(self, query: SearchQuery) -> AggregatedSearchResults:
    """
    Perform a federated search across multiple nodes.

Args:
    query: The search query

Returns:
    AggregatedSearchResults: Aggregated search results
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## vector_search

```python
async def vector_search(self, dataset_id: str, query_vector: List[float], top_k: int = 10, distance_metric: str = "cosine", min_similarity: float = 0.0, timeout_ms: int = 5000, include_metadata: bool = True) -> AggregatedSearchResults:
    """
    Perform a federated vector search.

Args:
    dataset_id: ID of the dataset to search
    query_vector: Vector to search for
    top_k: Maximum number of results to return
    distance_metric: Distance metric to use (cosine, l2, dot)
    min_similarity: Minimum similarity score for results
    timeout_ms: Timeout in milliseconds
    include_metadata: Whether to include metadata in results

Returns:
    AggregatedSearchResults: Search results
    """
```
* **Async:** True
* **Method:** True
* **Class:** FederatedSearch

## vector_similarity

```python
def vector_similarity(vec1: np.ndarray, vec2: np.ndarray, metric: str = "cosine") -> float:
    """
    Calculate similarity between two vectors.

Args:
    vec1: First vector
    vec2: Second vector
    metric: Similarity metric (cosine, l2, dot)

Returns:
    float: Similarity score
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
