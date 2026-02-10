# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/cache_tools/cache_tools.py'

Files last updated: 1751509215.4179525

Stub file last updated: 2025-07-07 01:10:13

## _get_namespace_stats

```python
def _get_namespace_stats() -> Dict[str, Any]:
    """
    Get statistics for each namespace.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## cache_embeddings

```python
async def cache_embeddings(text: str, model: str, embeddings: List[float], metadata: Optional[Dict[str, Any]] = None, ttl: int = 3600) -> Dict[str, Any]:
    """
    Cache embedding results for text and model combinations.

Args:
    text: Input text that was embedded
    model: Model used for embedding
    embeddings: Embedding vector
    metadata: Additional metadata to store
    ttl: Time to live in seconds
    
Returns:
    Dict containing caching results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## cache_stats

```python
async def cache_stats(namespace: Optional[str] = None) -> Dict[str, Any]:
    """
    Get detailed cache statistics and performance metrics.

Args:
    namespace: Optional namespace to filter stats. If None, returns global stats.
    
Returns:
    Dict containing cache statistics and performance metrics
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_cached_embeddings

```python
async def get_cached_embeddings(text: str, model: str) -> Dict[str, Any]:
    """
    Retrieve cached embeddings for text and model combination.

Args:
    text: Input text to find embeddings for
    model: Model used for embedding
    
Returns:
    Dict containing cached embeddings or miss result
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## manage_cache

```python
async def manage_cache(operation: str, key: Optional[str] = None, value: Optional[Any] = None, ttl: Optional[int] = None, namespace: str = "default") -> Dict[str, Any]:
    """
    Manage cache operations including get, set, delete, and clear.

Args:
    operation: Cache operation (get, set, delete, clear, stats, list)
    key: Cache key for get/set/delete operations
    value: Value to store (for set operation)
    ttl: Time to live in seconds (for set operation)
    namespace: Cache namespace for organization
    
Returns:
    Dict containing operation results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## optimize_cache

```python
async def optimize_cache(strategy: str = "lru", max_size_mb: Optional[int] = None, max_age_hours: Optional[int] = None) -> Dict[str, Any]:
    """
    Optimize cache performance through cleanup and reorganization.

Args:
    strategy: Optimization strategy (lru, lfu, size_based, age_based)
    max_size_mb: Maximum cache size in MB
    max_age_hours: Maximum age for cache entries in hours
    
Returns:
    Dict containing optimization results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
