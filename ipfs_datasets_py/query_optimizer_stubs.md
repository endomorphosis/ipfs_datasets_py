# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/query_optimizer.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 02:11:02

## HybridQueryOptimizer

```python
class HybridQueryOptimizer:
    """
    Optimizer for hybrid queries that combine vector and graph operations.

This optimizer coordinates:
1. Vector + graph hybrid queries
2. Dynamic balancing of vector and graph components
3. Performance metrics for hybrid operations
4. Joint optimization of both components
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IndexRegistry

```python
class IndexRegistry:
    """
    Registry of available indexes for query optimization.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## KnowledgeGraphQueryOptimizer

```python
class KnowledgeGraphQueryOptimizer:
    """
    Specialized optimizer for knowledge graph queries.

This optimizer focuses on:
1. Graph traversal optimization
2. Path planning for relationship queries
3. Caching of frequently accessed graph patterns
4. Node and relationship type-specific optimizations
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LRUQueryCache

```python
class LRUQueryCache:
    """
    LRU (Least Recently Used) cache for query results.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryMetrics

```python
@dataclass
class QueryMetrics:
    """
    Metrics for a single query execution.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryOptimizer

```python
class QueryOptimizer:
    """
    Query optimizer that uses statistics and indexes to improve query performance.

The optimizer works with various query types including:
- Vector searches
- Property/attribute searches
- Graph traversals
- Combined/hybrid searches
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryStatsCollector

```python
class QueryStatsCollector:
    """
    Collects and analyzes query performance statistics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## VectorIndexOptimizer

```python
class VectorIndexOptimizer:
    """
    Specialized optimizer for vector index operations.

This optimizer focuses on:
1. Dimension-specific optimizations
2. Vector index caching strategies
3. Approximate vs. exact search decisions
4. Parameter tuning for specific vector search algorithms
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, max_history: int = 1000):
    """
    Initialize the query statistics collector.

Args:
    max_history: Maximum number of query metrics to store in history
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryStatsCollector

## __init__

```python
def __init__(self, max_size: int = 100):
    """
    Initialize an LRU cache for query results.

Args:
    max_size: Maximum number of queries to cache
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUQueryCache

## __init__

```python
def __init__(self):
    """
    Initialize the index registry.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IndexRegistry

## __init__

```python
def __init__(self, stats_collector: Optional[QueryStatsCollector] = None, query_cache: Optional[LRUQueryCache] = None, index_registry: Optional[IndexRegistry] = None):
    """
    Initialize the query optimizer.

Args:
    stats_collector: Statistics collector, or create a new one if None
    query_cache: Query cache, or create a new one if None
    index_registry: Index registry, or create a new one if None
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## __init__

```python
def __init__(self, query_optimizer: QueryOptimizer):
    """
    Initialize the vector index optimizer.

Args:
    query_optimizer: Base query optimizer to extend
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorIndexOptimizer

## __init__

```python
def __init__(self, query_optimizer: QueryOptimizer):
    """
    Initialize the knowledge graph query optimizer.

Args:
    query_optimizer: Base query optimizer to extend
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphQueryOptimizer

## __init__

```python
def __init__(self, vector_optimizer: VectorIndexOptimizer, graph_optimizer: KnowledgeGraphQueryOptimizer):
    """
    Initialize the hybrid query optimizer.

Args:
    vector_optimizer: Vector index optimizer
    graph_optimizer: Knowledge graph query optimizer
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridQueryOptimizer

## _choose_best_index

```python
def _choose_best_index(self, query_type: str, query_params: Dict[str, Any], indexes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Choose the best index for a query based on statistics and query type.

Args:
    query_type: Type of query
    query_params: Query parameters
    indexes: List of suitable indexes

Returns:
    Best index or None if no suitable index found
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## _compute_adaptive_weights

```python
def _compute_adaptive_weights(self, query_params: Dict[str, Any]) -> Tuple[float, float]:
    """
    Compute adaptive weights for vector and graph components based on query history.

Args:
    query_params: Hybrid query parameters

Returns:
    Tuple of (vector_weight, graph_weight)
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridQueryOptimizer

## _create_query_id

```python
def _create_query_id(self, query_type: str, query_params: Dict[str, Any]) -> str:
    """
    Create a unique ID for a query.

Args:
    query_type: Type of query
    query_params: Query parameters

Returns:
    Unique query ID
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## _generate_key

```python
def _generate_key(self, query_type: str, query_params: Dict[str, Any]) -> str:
    """
    Generate a cache key for a query.

Args:
    query_type: Type of query
    query_params: Query parameters

Returns:
    Cache key string
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUQueryCache

## _plan_traversal_path

```python
def _plan_traversal_path(self, start_entity_type: Optional[str], relationship_types: List[str], max_depth: int) -> List[Dict[str, Any]]:
    """
    Plan an optimized traversal path based on statistics and costs.

Args:
    start_entity_type: Starting entity type
    relationship_types: Types of relationships to traverse
    max_depth: Maximum traversal depth

Returns:
    Planned traversal path
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphQueryOptimizer

## _update_averages

```python
def _update_averages(self) -> None:
    """
    Update average duration statistics for query types.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryStatsCollector

## complete

```python
def complete(self, result_count: int, scan_count: int, index_used: bool = False, index_name: Optional[str] = None, error: Optional[str] = None) -> None:
    """
    Complete the metrics after query execution.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetrics

## create_query_optimizer

```python
def create_query_optimizer(max_cache_size: int = 100, collect_statistics: bool = True, optimize_vectors: bool = True, optimize_graphs: bool = True, optimize_hybrid: bool = True) -> Dict[str, Any]:
    """
    Create a complete set of query optimizers.

Args:
    max_cache_size: Maximum size for query caches
    collect_statistics: Whether to collect statistics
    optimize_vectors: Whether to include vector optimization
    optimize_graphs: Whether to include graph optimization
    optimize_hybrid: Whether to include hybrid optimization

Returns:
    Dict containing all optimizers
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## execute_graph_query

```python
def execute_graph_query(self, query_params: Dict[str, Any], query_func: Callable, optimizations: Optional[Dict[str, Any]] = None) -> Tuple[Any, QueryMetrics]:
    """
    Execute an optimized knowledge graph query.

Args:
    query_params: Graph query parameters
    query_func: Function to execute the query
    optimizations: Optional graph query specific optimizations

Returns:
    Tuple of (query_results, query_metrics)
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphQueryOptimizer

## execute_hybrid_query

```python
def execute_hybrid_query(self, query_params: Dict[str, Any], vector_func: Callable, graph_func: Callable, merge_func: Callable, optimizations: Optional[Dict[str, Any]] = None) -> Tuple[Any, QueryMetrics]:
    """
    Execute a hybrid query with optimized components.

Args:
    query_params: Hybrid query parameters
    vector_func: Function to execute vector search
    graph_func: Function to execute graph query
    merge_func: Function to merge results
    optimizations: Optional hybrid query specific optimizations

Returns:
    Tuple of (query_results, query_metrics)
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridQueryOptimizer

## execute_query

```python
def execute_query(self, query_type: str, query_params: Dict[str, Any], query_func: Callable, optimizations: Optional[Dict[str, Any]] = None) -> Tuple[Any, QueryMetrics]:
    """
    Execute a query with optimization and collect metrics.

Args:
    query_type: Type of query
    query_params: Query parameters
    query_func: Function to execute the query
    optimizations: Optional query-specific optimizations

Returns:
    Tuple of (query_result, query_metrics)
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## execute_vector_search

```python
def execute_vector_search(self, query_params: Dict[str, Any], search_func: Callable, optimizations: Optional[Dict[str, Any]] = None) -> Tuple[Any, QueryMetrics]:
    """
    Execute an optimized vector search query.

Args:
    query_params: Vector search parameters
    search_func: Function to execute the search
    optimizations: Optional vector search specific optimizations

Returns:
    Tuple of (search_results, query_metrics)
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorIndexOptimizer

## find_indexes_for_fields

```python
def find_indexes_for_fields(self, fields: List[str]) -> List[Dict[str, Any]]:
    """
    Find indexes covering specified fields.

Args:
    fields: List of fields to look for

Returns:
    List of matching indexes
    """
```
* **Async:** False
* **Method:** True
* **Class:** IndexRegistry

## find_indexes_for_query

```python
def find_indexes_for_query(self, query_type: str, query_params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Find indexes suitable for a specific query.

Args:
    query_type: Type of query
    query_params: Query parameters

Returns:
    List of suitable indexes
    """
```
* **Async:** False
* **Method:** True
* **Class:** IndexRegistry

## get

```python
def get(self, query_type: str, query_params: Dict[str, Any]) -> Tuple[bool, Any]:
    """
    Get a result from the cache.

Args:
    query_type: Type of query
    query_params: Query parameters

Returns:
    Tuple of (cache_hit, result)
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUQueryCache

## get_all_indexes

```python
def get_all_indexes(self) -> List[Dict[str, Any]]:
    """
    Get all registered indexes.

Returns:
    List of all indexes
    """
```
* **Async:** False
* **Method:** True
* **Class:** IndexRegistry

## get_index

```python
def get_index(self, name: str) -> Optional[Dict[str, Any]]:
    """
    Get information about an index.

Args:
    name: Name of the index

Returns:
    Index information or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** IndexRegistry

## get_optimization_recommendations

```python
def get_optimization_recommendations(self) -> List[Dict[str, Any]]:
    """
    Generate recommendations for query optimizations based on statistics.

Returns:
    List of recommendations
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryStatsCollector

## get_optimization_recommendations

```python
def get_optimization_recommendations(self) -> List[Dict[str, Any]]:
    """
    Get optimization recommendations.

Returns:
    List of recommendations
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## get_query_statistics

```python
def get_query_statistics(self) -> Dict[str, Any]:
    """
    Get query statistics.

Returns:
    Statistics summary
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## get_stats_summary

```python
def get_stats_summary(self) -> Dict[str, Any]:
    """
    Get a summary of query statistics.

Returns:
    Dict containing summary statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryStatsCollector

## invalidate

```python
def invalidate(self, query_type: Optional[str] = None) -> None:
    """
    Invalidate cache entries for a query type or all entries.

Args:
    query_type: Type of query to invalidate, or None for all
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUQueryCache

## invalidate_cache

```python
def invalidate_cache(self, query_type: Optional[str] = None) -> None:
    """
    Invalidate query cache.

Args:
    query_type: Type of queries to invalidate, or None for all
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## invalidate_pattern_cache

```python
def invalidate_pattern_cache(self) -> None:
    """
    Invalidate the pattern cache.
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphQueryOptimizer

## optimize_graph_query

```python
def optimize_graph_query(self, query_params: Dict[str, Any], optimizations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Optimize a knowledge graph query.

Args:
    query_params: Graph query parameters
    optimizations: Optional graph query specific optimizations

Returns:
    Optimized query plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphQueryOptimizer

## optimize_hybrid_query

```python
def optimize_hybrid_query(self, query_params: Dict[str, Any], optimizations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Optimize a hybrid query that combines vector and graph operations.

Args:
    query_params: Hybrid query parameters
    optimizations: Optional hybrid query specific optimizations

Returns:
    Optimized query plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** HybridQueryOptimizer

## optimize_query

```python
def optimize_query(self, query_type: str, query_params: Dict[str, Any], optimizations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Optimize a query using statistics and indexes.

Args:
    query_type: Type of query
    query_params: Query parameters
    optimizations: Optional query-specific optimizations to override defaults

Returns:
    Optimized query plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## optimize_vector_search

```python
def optimize_vector_search(self, query_params: Dict[str, Any], optimizations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Optimize a vector search query.

Args:
    query_params: Vector search parameters
    optimizations: Optional vector search specific optimizations

Returns:
    Optimized query plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorIndexOptimizer

## put

```python
def put(self, query_type: str, query_params: Dict[str, Any], result: Any) -> None:
    """
    Add a result to the cache.

Args:
    query_type: Type of query
    query_params: Query parameters
    result: Query result to cache
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUQueryCache

## record_query

```python
def record_query(self, metrics: QueryMetrics) -> None:
    """
    Record metrics for a completed query.

Args:
    metrics: The query metrics to record
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryStatsCollector

## register_index

```python
def register_index(self, name: str, index_type: str, fields: List[str], metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Register an index.

Args:
    name: Name of the index
    index_type: Type of the index (e.g., 'btree', 'hash', 'vector')
    fields: List of fields covered by the index
    metadata: Optional metadata about the index
    """
```
* **Async:** False
* **Method:** True
* **Class:** IndexRegistry

## reset_statistics

```python
def reset_statistics(self) -> None:
    """
    Reset query statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryOptimizer

## reset_stats

```python
def reset_stats(self) -> None:
    """
    Reset all collected statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryStatsCollector

## set_entity_type_priority

```python
def set_entity_type_priority(self, entity_type: str, priority: int) -> None:
    """
    Set traversal priority for an entity type.

Args:
    entity_type: Entity type
    priority: Priority value (higher means traverse first)
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphQueryOptimizer

## size

```python
def size(self) -> int:
    """
    Get the current size of the cache.

Returns:
    Number of items in the cache
    """
```
* **Async:** False
* **Method:** True
* **Class:** LRUQueryCache

## tune_vector_index_params

```python
def tune_vector_index_params(self, dimension: int, performance_metrics: Dict[str, float]) -> Dict[str, Any]:
    """
    Tune vector index parameters based on performance metrics.

Args:
    dimension: Vector dimension
    performance_metrics: Performance metrics including search time, accuracy, etc.

Returns:
    Updated index parameters
    """
```
* **Async:** False
* **Method:** True
* **Class:** VectorIndexOptimizer

## unregister_index

```python
def unregister_index(self, name: str) -> bool:
    """
    Unregister an index.

Args:
    name: Name of the index to unregister

Returns:
    True if the index was unregistered, False if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** IndexRegistry

## update_relationship_costs

```python
def update_relationship_costs(self, costs: Dict[str, float]) -> None:
    """
    Update relationship traversal costs.

Args:
    costs: Mapping of relationship types to traversal costs
    """
```
* **Async:** False
* **Method:** True
* **Class:** KnowledgeGraphQueryOptimizer
