"""
Query Performance Optimizer

This module provides functionality for optimizing query performance with statistics
and indexes. It includes:

1. Query performance metrics collection
2. Index optimization for various query patterns
3. Query planning based on statistics
4. Caching mechanisms for frequently executed queries
5. Adaptive query optimization

The optimizations work with various data sources including IPLD storage,
vector indexes, and knowledge graph structures.
"""

import time
import json
import hashlib
import threading
import logging
from typing import Dict, List, Any, Optional, Tuple, Callable, Union, Set
from collections import defaultdict, deque
import numpy as np
from dataclasses import dataclass, field

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    """Metrics for a single query execution."""
    query_id: str
    query_type: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    result_count: int = 0
    scan_count: int = 0
    cache_hit: bool = False
    index_used: bool = False
    index_name: Optional[str] = None
    filter_count: int = 0
    execution_plan: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def complete(self, result_count: int, scan_count: int, index_used: bool = False,
                index_name: Optional[str] = None, error: Optional[str] = None) -> None:
        """Complete the metrics after query execution."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.result_count = result_count
        self.scan_count = scan_count
        self.index_used = index_used
        self.index_name = index_name
        self.error = error


class QueryStatsCollector:
    """Collects and analyzes query performance statistics."""

    def __init__(self, max_history: int = 1000):
        """
        Initialize the query statistics collector.

        Args:
            max_history: Maximum number of query metrics to store in history
        """
        self.metrics_history: deque = deque(maxlen=max_history)
        self.query_types: Dict[str, int] = defaultdict(int)
        self.avg_duration_by_type: Dict[str, float] = {}
        self.index_usage: Dict[str, int] = defaultdict(int)
        self.cache_hit_count: int = 0
        self.cache_miss_count: int = 0
        self.total_queries: int = 0
        self.error_count: int = 0
        self._lock = threading.RLock()

    def record_query(self, metrics: QueryMetrics) -> None:
        """
        Record metrics for a completed query.

        Args:
            metrics: The query metrics to record
        """
        with self._lock:
            self.metrics_history.append(metrics)
            self.query_types[metrics.query_type] += 1
            self.total_queries += 1

            if metrics.error:
                self.error_count += 1

            if metrics.cache_hit:
                self.cache_hit_count += 1
            else:
                self.cache_miss_count += 1

            if metrics.index_used and metrics.index_name:
                self.index_name = metrics.index_name
                self.index_usage[metrics.index_name] += 1

            # Update average durations
            self._update_averages()

    def _update_averages(self) -> None:
        """Update average duration statistics for query types."""
        for query_type in self.query_types:
            type_metrics = [m for m in self.metrics_history if m.query_type == query_type and not m.error]
            if type_metrics:
                self.avg_duration_by_type[query_type] = sum(m.duration_ms for m in type_metrics) / len(type_metrics)

    def get_stats_summary(self) -> Dict[str, Any]:
        """
        Get a summary of query statistics.

        Returns:
            Dict containing summary statistics
        """
        with self._lock:
            if not self.total_queries:
                return {"total_queries": 0, "message": "No queries recorded yet"}

            cache_hit_rate = self.cache_hit_count / self.total_queries if self.total_queries > 0 else 0
            error_rate = self.error_count / self.total_queries if self.total_queries > 0 else 0

            # Calculate percentiles for query duration
            if self.metrics_history:
                durations = [m.duration_ms for m in self.metrics_history if not m.error]
                p50 = np.percentile(durations, 50) if durations else 0
                p90 = np.percentile(durations, 90) if durations else 0
                p99 = np.percentile(durations, 99) if durations else 0
            else:
                p50, p90, p99 = 0, 0, 0

            # Find slowest queries
            slowest = sorted(
                [m for m in self.metrics_history if not m.error],
                key=lambda m: m.duration_ms,
                reverse=True
            )[:5]

            # Most frequent query types
            query_type_counts = sorted(
                [(qtype, count) for qtype, count in self.query_types.items()],
                key=lambda x: x[1],
                reverse=True
            )

            return {
                "total_queries": self.total_queries,
                "query_type_distribution": dict(query_type_counts),
                "avg_duration_by_type": self.avg_duration_by_type,
                "cache_hit_rate": cache_hit_rate,
                "error_rate": error_rate,
                "index_usage": dict(self.index_usage),
                "percentiles": {
                    "p50_ms": p50,
                    "p90_ms": p90,
                    "p99_ms": p99
                },
                "slowest_queries": [
                    {
                        "query_id": q.query_id,
                        "query_type": q.query_type,
                        "duration_ms": q.duration_ms,
                        "result_count": q.result_count,
                        "scan_count": q.scan_count
                    } for q in slowest
                ]
            }

    def get_optimization_recommendations(self) -> List[Dict[str, Any]]:
        """
        Generate recommendations for query optimizations based on statistics.

        Returns:
            List of recommendations
        """
        with self._lock:
            recommendations = []

            if not self.metrics_history:
                return [{"message": "Insufficient data for recommendations"}]

            # Find queries with high scan counts relative to result counts
            high_scan_queries = [
                m for m in self.metrics_history
                if m.scan_count > 100 and m.result_count > 0 and m.scan_count / m.result_count > 10
            ]

            if high_scan_queries:
                rec_types = set(q.query_type for q in high_scan_queries)
                recommendations.append({
                    "type": "index_recommendation",
                    "message": f"Consider adding indexes for query types: {', '.join(rec_types)}",
                    "affected_queries": len(high_scan_queries),
                    "query_types": list(rec_types)
                })

            # Identify slow query types
            slow_query_types = {}
            for qtype, avg_duration in self.avg_duration_by_type.items():
                if avg_duration > 100:  # More than 100ms is considered slow
                    slow_query_types[qtype] = avg_duration

            if slow_query_types:
                recommendations.append({
                    "type": "performance_warning",
                    "message": f"Slow query types detected",
                    "slow_types": slow_query_types
                })

            # Check cache efficiency
            if self.total_queries > 20:
                cache_hit_rate = self.cache_hit_count / self.total_queries
                if cache_hit_rate < 0.5:
                    recommendations.append({
                        "type": "cache_recommendation",
                        "message": "Low cache hit rate. Consider reviewing cache strategy.",
                        "current_hit_rate": cache_hit_rate
                    })

            return recommendations

    def reset_stats(self) -> None:
        """Reset all collected statistics."""
        with self._lock:
            self.metrics_history.clear()
            self.query_types.clear()
            self.avg_duration_by_type.clear()
            self.index_usage.clear()
            self.cache_hit_count = 0
            self.cache_miss_count = 0
            self.total_queries = 0
            self.error_count = 0


class LRUQueryCache:
    """LRU (Least Recently Used) cache for query results."""

    def __init__(self, max_size: int = 100):
        """
        Initialize an LRU cache for query results.

        Args:
            max_size: Maximum number of queries to cache
        """
        self.max_size = max_size
        self._cache: Dict[str, Any] = {}
        self._usage_order: List[str] = []
        self._lock = threading.RLock()

    def _generate_key(self, query_type: str, query_params: Dict[str, Any]) -> str:
        """
        Generate a cache key for a query.

        Args:
            query_type: Type of query
            query_params: Query parameters

        Returns:
            Cache key string
        """
        # Sort the params to ensure consistent keys
        param_str = json.dumps(query_params, sort_keys=True)
        return f"{query_type}:{param_str}"

    def get(self, query_type: str, query_params: Dict[str, Any]) -> Tuple[bool, Any]:
        """
        Get a result from the cache.

        Args:
            query_type: Type of query
            query_params: Query parameters

        Returns:
            Tuple of (cache_hit, result)
        """
        key = self._generate_key(query_type, query_params)

        with self._lock:
            if key in self._cache:
                # Update usage order
                self._usage_order.remove(key)
                self._usage_order.append(key)
                return True, self._cache[key]

            return False, None

    def put(self, query_type: str, query_params: Dict[str, Any], result: Any) -> None:
        """
        Add a result to the cache.

        Args:
            query_type: Type of query
            query_params: Query parameters
            result: Query result to cache
        """
        key = self._generate_key(query_type, query_params)

        with self._lock:
            if key in self._cache:
                # Update existing entry
                self._usage_order.remove(key)
            elif len(self._cache) >= self.max_size:
                # Remove least recently used item
                lru_key = self._usage_order.pop(0)
                del self._cache[lru_key]

            # Add new entry
            self._cache[key] = result
            self._usage_order.append(key)

    def invalidate(self, query_type: Optional[str] = None) -> None:
        """
        Invalidate cache entries for a query type or all entries.

        Args:
            query_type: Type of query to invalidate, or None for all
        """
        with self._lock:
            if query_type is None:
                self._cache.clear()
                self._usage_order.clear()
            else:
                # Remove entries matching the query type
                keys_to_remove = [k for k in self._cache if k.startswith(f"{query_type}:")]
                for key in keys_to_remove:
                    del self._cache[key]
                    self._usage_order.remove(key)

    def size(self) -> int:
        """
        Get the current size of the cache.

        Returns:
            Number of items in the cache
        """
        return len(self._cache)


class IndexRegistry:
    """Registry of available indexes for query optimization."""

    def __init__(self):
        """Initialize the index registry."""
        self.indexes: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def register_index(self, name: str, index_type: str, fields: List[str],
                      metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Register an index.

        Args:
            name: Name of the index
            index_type: Type of the index (e.g., 'btree', 'hash', 'vector')
            fields: List of fields covered by the index
            metadata: Optional metadata about the index
        """
        with self._lock:
            self.indexes[name] = {
                "name": name,
                "type": index_type,
                "fields": fields,
                "metadata": metadata or {},
                "created_at": time.time()
            }

    def unregister_index(self, name: str) -> bool:
        """
        Unregister an index.

        Args:
            name: Name of the index to unregister

        Returns:
            True if the index was unregistered, False if not found
        """
        with self._lock:
            if name in self.indexes:
                del self.indexes[name]
                return True
            return False

    def get_index(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get information about an index.

        Args:
            name: Name of the index

        Returns:
            Index information or None if not found
        """
        with self._lock:
            return self.indexes.get(name)

    def find_indexes_for_fields(self, fields: List[str]) -> List[Dict[str, Any]]:
        """
        Find indexes covering specified fields.

        Args:
            fields: List of fields to look for

        Returns:
            List of matching indexes
        """
        with self._lock:
            matching_indexes = []
            for index_info in self.indexes.values():
                # Check if all specified fields are covered by the index
                if all(field in index_info["fields"] for field in fields):
                    matching_indexes.append(index_info)
            return matching_indexes

    def find_indexes_for_query(self, query_type: str, query_params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Find indexes suitable for a specific query.

        Args:
            query_type: Type of query
            query_params: Query parameters

        Returns:
            List of suitable indexes
        """
        with self._lock:
            # Extract fields used in the query
            fields = []

            # Handle different query types
            if query_type == "vector_search":
                # For vector search, consider vector index
                return [idx for idx in self.indexes.values() if idx["type"] == "vector"]
            elif query_type == "property_search":
                # For property search, extract field names from filters
                if "filters" in query_params:
                    for f in query_params["filters"]:
                        if isinstance(f, dict) and "field" in f:
                            fields.append(f["field"])
            elif query_type == "graph_traversal":
                # For graph traversal, consider relationship fields
                if "start_node_type" in query_params:
                    fields.append(query_params["start_node_type"])
                if "relationship_types" in query_params:
                    fields.extend(query_params["relationship_types"])

            # Find indexes covering these fields
            return self.find_indexes_for_fields(fields)

    def get_all_indexes(self) -> List[Dict[str, Any]]:
        """
        Get all registered indexes.

        Returns:
            List of all indexes
        """
        with self._lock:
            return list(self.indexes.values())


class QueryOptimizer:
    """
    Query optimizer that uses statistics and indexes to improve query performance.

    The optimizer works with various query types including:
    - Vector searches
    - Property/attribute searches
    - Graph traversals
    - Combined/hybrid searches
    """

    def __init__(self, stats_collector: Optional[QueryStatsCollector] = None,
                query_cache: Optional[LRUQueryCache] = None,
                index_registry: Optional[IndexRegistry] = None):
        """
        Initialize the query optimizer.

        Args:
            stats_collector: Statistics collector, or create a new one if None
            query_cache: Query cache, or create a new one if None
            index_registry: Index registry, or create a new one if None
        """
        self.stats = stats_collector or QueryStatsCollector()
        self.cache = query_cache or LRUQueryCache()
        self.index_registry = index_registry or IndexRegistry()
        self.default_optimizations = {
            "use_cache": True,
            "use_indexes": True,
            "limit_scan": True,
            "max_scan_count": 10000,
            "adaptive_optimization": True
        }

    def _create_query_id(self, query_type: str, query_params: Dict[str, Any]) -> str:
        """
        Create a unique ID for a query.

        Args:
            query_type: Type of query
            query_params: Query parameters

        Returns:
            Unique query ID
        """
        param_str = json.dumps(query_params, sort_keys=True)
        query_hash = hashlib.md5(f"{query_type}:{param_str}".encode()).hexdigest()
        return f"{query_type}_{query_hash[:8]}"

    def optimize_query(self, query_type: str, query_params: Dict[str, Any],
                      optimizations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Optimize a query using statistics and indexes.

        Args:
            query_type: Type of query
            query_params: Query parameters
            optimizations: Optional query-specific optimizations to override defaults

        Returns:
            Optimized query plan
        """
        # Start timing the optimization
        start_time = time.time()

        # Combine default optimizations with query-specific ones
        opts = self.default_optimizations.copy()
        if optimizations:
            opts.update(optimizations)

        # Create query ID
        query_id = self._create_query_id(query_type, query_params)

        # Initialize query plan
        query_plan = {
            "query_id": query_id,
            "query_type": query_type,
            "original_params": query_params,
            "optimized_params": query_params.copy(),
            "use_cache": opts["use_cache"],
            "use_indexes": opts["use_indexes"],
            "indexes": [],
            "limit_scan": opts["limit_scan"],
            "max_scan_count": opts["max_scan_count"],
            "optimization_time_ms": 0
        }

        # Find suitable indexes
        if opts["use_indexes"]:
            suitable_indexes = self.index_registry.find_indexes_for_query(query_type, query_params)
            if suitable_indexes:
                # Choose the best index based on statistics and query type
                best_index = self._choose_best_index(query_type, query_params, suitable_indexes)
                if best_index:
                    query_plan["indexes"].append(best_index["name"])
                    # Adjust query parameters to use the index
                    query_plan["optimized_params"]["use_index"] = best_index["name"]

        # Adaptive optimization based on past statistics
        if opts["adaptive_optimization"] and query_type in self.stats.avg_duration_by_type:
            avg_duration = self.stats.avg_duration_by_type[query_type]
            if avg_duration > 500:  # If average duration is over 500ms
                # Reduce scan limit for expensive queries
                query_plan["max_scan_count"] = min(1000, query_plan["max_scan_count"])
                logger.info(f"Reducing scan limit for expensive query type {query_type}")

        # Calculate optimization time
        end_time = time.time()
        query_plan["optimization_time_ms"] = (end_time - start_time) * 1000

        return query_plan

    def _choose_best_index(self, query_type: str, query_params: Dict[str, Any],
                         indexes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Choose the best index for a query based on statistics and query type.

        Args:
            query_type: Type of query
            query_params: Query parameters
            indexes: List of suitable indexes

        Returns:
            Best index or None if no suitable index found
        """
        if not indexes:
            return None

        # For vector search, prioritize vector indexes
        if query_type == "vector_search":
            vector_indexes = [idx for idx in indexes if idx["type"] == "vector"]
            if vector_indexes:
                # Check if the index has the right dimension
                if "dimension" in query_params and "metadata" in vector_indexes[0]:
                    metadata = vector_indexes[0]["metadata"]
                    if "dimension" in metadata and metadata["dimension"] == query_params["dimension"]:
                        return vector_indexes[0]
                else:
                    return vector_indexes[0]

        # For property search, prioritize btree indexes
        elif query_type == "property_search":
            btree_indexes = [idx for idx in indexes if idx["type"] == "btree"]
            if btree_indexes:
                return btree_indexes[0]

        # For graph traversal, prioritize graph indexes
        elif query_type == "graph_traversal":
            graph_indexes = [idx for idx in indexes if idx["type"] == "graph"]
            if graph_indexes:
                return graph_indexes[0]

        # Default to first index if no specific logic applies
        return indexes[0] if indexes else None

    def execute_query(self, query_type: str, query_params: Dict[str, Any],
                     query_func: Callable, optimizations: Optional[Dict[str, Any]] = None) -> Tuple[Any, QueryMetrics]:
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
        # Check cache first if enabled
        opts = self.default_optimizations.copy()
        if optimizations:
            opts.update(optimizations)

        query_id = self._create_query_id(query_type, query_params)
        metrics = QueryMetrics(
            query_id=query_id,
            query_type=query_type,
            start_time=time.time()
        )

        # Try cache first
        if opts["use_cache"]:
            cache_hit, cached_result = self.cache.get(query_type, query_params)
            if cache_hit:
                metrics.cache_hit = True
                metrics.complete(
                    result_count=len(cached_result) if isinstance(cached_result, (list, tuple)) else 1,
                    scan_count=0
                )
                self.stats.record_query(metrics)
                return cached_result, metrics

        # Optimize the query
        query_plan = self.optimize_query(query_type, query_params, optimizations)
        metrics.execution_plan = query_plan

        # Execute the optimized query
        try:
            result = query_func(query_plan["optimized_params"])

            # Determine result and scan counts
            result_count = len(result) if isinstance(result, (list, tuple)) else 1

            # Scan count would typically come from the query execution
            # Here we're using a placeholder assuming it's reported by the query function
            scan_count = getattr(result, "scan_count", result_count * 2)

            # Record index usage
            index_used = bool(query_plan["indexes"])
            index_name = query_plan["indexes"][0] if query_plan["indexes"] else None

            # Complete metrics
            metrics.complete(
                result_count=result_count,
                scan_count=scan_count,
                index_used=index_used,
                index_name=index_name
            )

            # Cache the result if enabled
            if opts["use_cache"]:
                self.cache.put(query_type, query_params, result)

        except Exception as e:
            logger.error(f"Error executing query {query_id}: {str(e)}")
            metrics.complete(
                result_count=0,
                scan_count=0,
                error=str(e)
            )
            raise
        finally:
            # Record the metrics whether successful or not
            self.stats.record_query(metrics)

        return result, metrics

    def get_query_statistics(self) -> Dict[str, Any]:
        """
        Get query statistics.

        Returns:
            Statistics summary
        """
        return self.stats.get_stats_summary()

    def get_optimization_recommendations(self) -> List[Dict[str, Any]]:
        """
        Get optimization recommendations.

        Returns:
            List of recommendations
        """
        return self.stats.get_optimization_recommendations()

    def invalidate_cache(self, query_type: Optional[str] = None) -> None:
        """
        Invalidate query cache.

        Args:
            query_type: Type of queries to invalidate, or None for all
        """
        self.cache.invalidate(query_type)

    def reset_statistics(self) -> None:
        """Reset query statistics."""
        self.stats.reset_stats()


class VectorIndexOptimizer:
    """
    Specialized optimizer for vector index operations.

    This optimizer focuses on:
    1. Dimension-specific optimizations
    2. Vector index caching strategies
    3. Approximate vs. exact search decisions
    4. Parameter tuning for specific vector search algorithms
    """

    def __init__(self, query_optimizer: QueryOptimizer):
        """
        Initialize the vector index optimizer.

        Args:
            query_optimizer: Base query optimizer to extend
        """
        self.query_optimizer = query_optimizer
        self.vector_index_settings = {
            "default_ef_search": 100,
            "default_ef_construction": 200,
            "default_m": 16,
            "prefer_exact_search_below_dim": 50,
            "prefer_approximate_search_above_dim": 100,
            "max_vector_cache_items": 1000,
            "min_vectors_for_index": 100,
            "dimension_to_index_params": {
                # dimension: (ef_search, ef_construction, m)
                128: (80, 160, 16),
                256: (100, 200, 16),
                384: (120, 240, 32),
                512: (140, 280, 32),
                768: (160, 320, 64),
                1024: (200, 400, 64),
                1536: (300, 600, 96),
            }
        }

    def optimize_vector_search(self, query_params: Dict[str, Any],
                              optimizations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Optimize a vector search query.

        Args:
            query_params: Vector search parameters
            optimizations: Optional vector search specific optimizations

        Returns:
            Optimized query plan
        """
        # Use the base optimizer first
        base_plan = self.query_optimizer.optimize_query("vector_search", query_params, optimizations)

        # Add vector-specific optimizations
        dimension = query_params.get("dimension", 0)
        exact_search = False

        # Decide between exact and approximate search based on dimension
        if dimension <= self.vector_index_settings["prefer_exact_search_below_dim"]:
            exact_search = True

        # Tune search parameters based on dimension
        if dimension in self.vector_index_settings["dimension_to_index_params"]:
            ef_search, ef_construction, m = self.vector_index_settings["dimension_to_index_params"][dimension]
        else:
            ef_search = self.vector_index_settings["default_ef_search"]
            ef_construction = self.vector_index_settings["default_ef_construction"]
            m = self.vector_index_settings["default_m"]

        # Update the optimized parameters
        optimized_params = base_plan["optimized_params"]
        optimized_params["exact_search"] = exact_search
        optimized_params["ef_search"] = ef_search

        # Include information about the parameters in the plan
        base_plan["vector_specific"] = {
            "dimension": dimension,
            "exact_search": exact_search,
            "ef_search": ef_search,
            "ef_construction": ef_construction,
            "m": m
        }

        return base_plan

    def execute_vector_search(self, query_params: Dict[str, Any],
                             search_func: Callable,
                             optimizations: Optional[Dict[str, Any]] = None) -> Tuple[Any, QueryMetrics]:
        """
        Execute an optimized vector search query.

        Args:
            query_params: Vector search parameters
            search_func: Function to execute the search
            optimizations: Optional vector search specific optimizations

        Returns:
            Tuple of (search_results, query_metrics)
        """
        # Optimize the query parameters
        optimized_plan = self.optimize_vector_search(query_params, optimizations)

        # Execute using the base optimizer
        return self.query_optimizer.execute_query(
            query_type="vector_search",
            query_params=optimized_plan["optimized_params"],
            query_func=search_func,
            optimizations=optimizations
        )

    def tune_vector_index_params(self, dimension: int, performance_metrics: Dict[str, float]) -> Dict[str, Any]:
        """
        Tune vector index parameters based on performance metrics.

        Args:
            dimension: Vector dimension
            performance_metrics: Performance metrics including search time, accuracy, etc.

        Returns:
            Updated index parameters
        """
        # Get current parameters
        if dimension in self.vector_index_settings["dimension_to_index_params"]:
            ef_search, ef_construction, m = self.vector_index_settings["dimension_to_index_params"][dimension]
        else:
            ef_search = self.vector_index_settings["default_ef_search"]
            ef_construction = self.vector_index_settings["default_ef_construction"]
            m = self.vector_index_settings["default_m"]

        # Tune based on metrics
        avg_search_time = performance_metrics.get("avg_search_time_ms", 0)
        avg_accuracy = performance_metrics.get("avg_accuracy", 0)

        # If search is too slow but accuracy is high, reduce ef_search
        if avg_search_time > 10 and avg_accuracy > 0.95:
            ef_search = max(40, ef_search - 20)

        # If accuracy is too low, increase ef_search
        elif avg_accuracy < 0.9 and avg_search_time < 5:
            ef_search = min(400, ef_search + 20)

        # Update settings
        self.vector_index_settings["dimension_to_index_params"][dimension] = (ef_search, ef_construction, m)

        return {
            "dimension": dimension,
            "ef_search": ef_search,
            "ef_construction": ef_construction,
            "m": m
        }


class KnowledgeGraphQueryOptimizer:
    """
    Specialized optimizer for knowledge graph queries.

    This optimizer focuses on:
    1. Graph traversal optimization
    2. Path planning for relationship queries
    3. Caching of frequently accessed graph patterns
    4. Node and relationship type-specific optimizations
    """

    def __init__(self, query_optimizer: QueryOptimizer):
        """
        Initialize the knowledge graph query optimizer.

        Args:
            query_optimizer: Base query optimizer to extend
        """
        self.query_optimizer = query_optimizer
        self.graph_optimization_settings = {
            "max_traverse_depth": 3,
            "cache_frequent_patterns": True,
            "max_pattern_cache_size": 100,
            "entity_type_priorities": {},
            "relationship_type_costs": {},
            "default_relationship_cost": 1.0,
            "cache_entity_properties": True,
            "batch_size_for_path_queries": 50
        }
        self.pattern_cache = LRUQueryCache(max_size=self.graph_optimization_settings["max_pattern_cache_size"])

    def optimize_graph_query(self, query_params: Dict[str, Any],
                           optimizations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Optimize a knowledge graph query.

        Args:
            query_params: Graph query parameters
            optimizations: Optional graph query specific optimizations

        Returns:
            Optimized query plan
        """
        # Use the base optimizer first
        base_plan = self.query_optimizer.optimize_query("graph_traversal", query_params, optimizations)

        # Add graph-specific optimizations
        query_type = query_params.get("query_type", "traversal")
        start_entity_type = query_params.get("start_entity_type")
        relationship_types = query_params.get("relationship_types", [])
        max_depth = min(
            query_params.get("max_depth", self.graph_optimization_settings["max_traverse_depth"]),
            self.graph_optimization_settings["max_traverse_depth"]
        )

        # Plan traversal path
        path_plan = self._plan_traversal_path(start_entity_type, relationship_types, max_depth)

        # Update the optimized parameters
        optimized_params = base_plan["optimized_params"]
        optimized_params["max_depth"] = max_depth
        optimized_params["path_plan"] = path_plan

        if "batch_size" not in optimized_params:
            optimized_params["batch_size"] = self.graph_optimization_settings["batch_size_for_path_queries"]

        # Include information about the graph-specific plan
        base_plan["graph_specific"] = {
            "query_type": query_type,
            "start_entity_type": start_entity_type,
            "path_plan": path_plan,
            "max_depth": max_depth
        }

        return base_plan

    def _plan_traversal_path(self, start_entity_type: Optional[str],
                           relationship_types: List[str], max_depth: int) -> List[Dict[str, Any]]:
        """
        Plan an optimized traversal path based on statistics and costs.

        Args:
            start_entity_type: Starting entity type
            relationship_types: Types of relationships to traverse
            max_depth: Maximum traversal depth

        Returns:
            Planned traversal path
        """
        path_plan = []

        # If no entity type, use a general traversal
        if not start_entity_type:
            for depth in range(max_depth):
                path_plan.append({
                    "depth": depth + 1,
                    "relationship_types": relationship_types,
                    "estimated_cost": len(relationship_types) * self.graph_optimization_settings["default_relationship_cost"]
                })
            return path_plan

        # Get relationship costs
        rel_costs = self.graph_optimization_settings["relationship_type_costs"]
        default_cost = self.graph_optimization_settings["default_relationship_cost"]

        # Plan each step
        for depth in range(max_depth):
            step_cost = 0
            for rel_type in relationship_types:
                step_cost += rel_costs.get(rel_type, default_cost)

            path_plan.append({
                "depth": depth + 1,
                "relationship_types": relationship_types,
                "estimated_cost": step_cost
            })

        return path_plan

    def execute_graph_query(self, query_params: Dict[str, Any],
                          query_func: Callable,
                          optimizations: Optional[Dict[str, Any]] = None) -> Tuple[Any, QueryMetrics]:
        """
        Execute an optimized knowledge graph query.

        Args:
            query_params: Graph query parameters
            query_func: Function to execute the query
            optimizations: Optional graph query specific optimizations

        Returns:
            Tuple of (query_results, query_metrics)
        """
        # Check pattern cache first
        if self.graph_optimization_settings["cache_frequent_patterns"]:
            cache_hit, cached_result = self.pattern_cache.get("graph_pattern", query_params)
            if cache_hit:
                # Create a new metrics object for this cache hit
                query_id = self.query_optimizer._create_query_id("graph_traversal", query_params)
                metrics = QueryMetrics(
                    query_id=query_id,
                    query_type="graph_traversal",
                    start_time=time.time(),
                    cache_hit=True
                )
                metrics.complete(
                    result_count=len(cached_result) if isinstance(cached_result, (list, tuple)) else 1,
                    scan_count=0
                )
                self.query_optimizer.stats.record_query(metrics)
                return cached_result, metrics

        # Optimize the query
        optimized_plan = self.optimize_graph_query(query_params, optimizations)

        # Execute using the base optimizer
        result, metrics = self.query_optimizer.execute_query(
            query_type="graph_traversal",
            query_params=optimized_plan["optimized_params"],
            query_func=query_func,
            optimizations=optimizations
        )

        # Cache the pattern result if successful and pattern caching enabled
        if not metrics.error and self.graph_optimization_settings["cache_frequent_patterns"]:
            self.pattern_cache.put("graph_pattern", query_params, result)

        return result, metrics

    def update_relationship_costs(self, costs: Dict[str, float]) -> None:
        """
        Update relationship traversal costs.

        Args:
            costs: Mapping of relationship types to traversal costs
        """
        self.graph_optimization_settings["relationship_type_costs"].update(costs)

    def set_entity_type_priority(self, entity_type: str, priority: int) -> None:
        """
        Set traversal priority for an entity type.

        Args:
            entity_type: Entity type
            priority: Priority value (higher means traverse first)
        """
        self.graph_optimization_settings["entity_type_priorities"][entity_type] = priority

    def invalidate_pattern_cache(self) -> None:
        """Invalidate the pattern cache."""
        self.pattern_cache.invalidate()


class HybridQueryOptimizer:
    """
    Optimizer for hybrid queries that combine vector and graph operations.

    This optimizer coordinates:
    1. Vector + graph hybrid queries
    2. Dynamic balancing of vector and graph components
    3. Performance metrics for hybrid operations
    4. Joint optimization of both components
    """

    def __init__(self, vector_optimizer: VectorIndexOptimizer,
                graph_optimizer: KnowledgeGraphQueryOptimizer):
        """
        Initialize the hybrid query optimizer.

        Args:
            vector_optimizer: Vector index optimizer
            graph_optimizer: Knowledge graph query optimizer
        """
        self.vector_optimizer = vector_optimizer
        self.graph_optimizer = graph_optimizer
        self.query_optimizer = vector_optimizer.query_optimizer  # Shared base optimizer
        self.hybrid_settings = {
            "default_vector_weight": 0.6,
            "default_graph_weight": 0.4,
            "adaptive_weighting": True,
            "min_vector_weight": 0.3,
            "max_vector_weight": 0.8,
            "query_context_size": 10,
            "query_history": []
        }

    def optimize_hybrid_query(self, query_params: Dict[str, Any],
                            optimizations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Optimize a hybrid query that combines vector and graph operations.

        Args:
            query_params: Hybrid query parameters
            optimizations: Optional hybrid query specific optimizations

        Returns:
            Optimized query plan
        """
        # Extract vector and graph components
        vector_params = query_params.get("vector_component", {})
        graph_params = query_params.get("graph_component", {})

        # Get weights
        vector_weight = query_params.get("vector_weight", self.hybrid_settings["default_vector_weight"])
        graph_weight = query_params.get("graph_weight", self.hybrid_settings["default_graph_weight"])

        # Use the individual optimizers
        vector_plan = self.vector_optimizer.optimize_vector_search(vector_params, optimizations)
        graph_plan = self.graph_optimizer.optimize_graph_query(graph_params, optimizations)

        # Adjust weights if adaptive weighting is enabled
        if self.hybrid_settings["adaptive_weighting"]:
            vector_weight, graph_weight = self._compute_adaptive_weights(query_params)

        # Create the hybrid plan
        hybrid_plan = {
            "query_id": self.query_optimizer._create_query_id("hybrid_search", query_params),
            "query_type": "hybrid_search",
            "original_params": query_params,
            "optimized_params": {
                "vector_component": vector_plan["optimized_params"],
                "graph_component": graph_plan["optimized_params"],
                "vector_weight": vector_weight,
                "graph_weight": graph_weight,
                "result_merging": "weighted_sum"
            },
            "component_plans": {
                "vector": vector_plan,
                "graph": graph_plan
            },
            "adaptive_weights": {
                "vector": vector_weight,
                "graph": graph_weight
            }
        }

        return hybrid_plan

    def _compute_adaptive_weights(self, query_params: Dict[str, Any]) -> Tuple[float, float]:
        """
        Compute adaptive weights for vector and graph components based on query history.

        Args:
            query_params: Hybrid query parameters

        Returns:
            Tuple of (vector_weight, graph_weight)
        """
        vector_weight = self.hybrid_settings["default_vector_weight"]
        graph_weight = self.hybrid_settings["default_graph_weight"]

        # Get query statistics
        query_stats = self.query_optimizer.get_query_statistics()

        # Adjust weights based on past performance if we have enough history
        if "query_type_distribution" in query_stats:
            if "vector_search" in query_stats["avg_duration_by_type"] and "graph_traversal" in query_stats["avg_duration_by_type"]:
                vector_time = query_stats["avg_duration_by_type"]["vector_search"]
                graph_time = query_stats["avg_duration_by_type"]["graph_traversal"]

                # If vector search is much faster, increase its weight
                if vector_time < graph_time * 0.5:
                    vector_weight = min(self.hybrid_settings["max_vector_weight"], vector_weight * 1.2)
                    graph_weight = 1.0 - vector_weight

                # If graph traversal is much faster, increase its weight
                elif graph_time < vector_time * 0.5:
                    graph_weight = min(1.0 - self.hybrid_settings["min_vector_weight"], graph_weight * 1.2)
                    vector_weight = 1.0 - graph_weight

        # Update history
        self.hybrid_settings["query_history"].append({
            "vector_weight": vector_weight,
            "graph_weight": graph_weight,
            "timestamp": time.time()
        })

        # Trim history if needed
        if len(self.hybrid_settings["query_history"]) > self.hybrid_settings["query_context_size"]:
            self.hybrid_settings["query_history"] = self.hybrid_settings["query_history"][-self.hybrid_settings["query_context_size"]:]

        return vector_weight, graph_weight

    def execute_hybrid_query(self, query_params: Dict[str, Any],
                           vector_func: Callable, graph_func: Callable, merge_func: Callable,
                           optimizations: Optional[Dict[str, Any]] = None) -> Tuple[Any, QueryMetrics]:
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
        # Start timing
        start_time = time.time()
        query_id = self.query_optimizer._create_query_id("hybrid_search", query_params)

        # Create metrics object
        metrics = QueryMetrics(
            query_id=query_id,
            query_type="hybrid_search",
            start_time=start_time
        )

        try:
            # Optimize the query
            hybrid_plan = self.optimize_hybrid_query(query_params, optimizations)
            metrics.execution_plan = hybrid_plan

            # Extract optimized parameters
            optimized_params = hybrid_plan["optimized_params"]
            vector_params = optimized_params["vector_component"]
            graph_params = optimized_params["graph_component"]
            vector_weight = optimized_params["vector_weight"]
            graph_weight = optimized_params["graph_weight"]

            # Execute vector component
            vector_result, vector_metrics = self.vector_optimizer.execute_vector_search(
                vector_params, vector_func
            )

            # Execute graph component
            graph_result, graph_metrics = self.graph_optimizer.execute_graph_query(
                graph_params, graph_func
            )

            # Merge results
            merged_result = merge_func(vector_result, graph_result, vector_weight, graph_weight)

            # Complete metrics
            result_count = len(merged_result) if isinstance(merged_result, (list, tuple)) else 1
            scan_count = vector_metrics.scan_count + graph_metrics.scan_count

            metrics.complete(
                result_count=result_count,
                scan_count=scan_count,
                index_used=vector_metrics.index_used or graph_metrics.index_used,
                index_name=vector_metrics.index_name or graph_metrics.index_name
            )

            # Store component metrics for analysis
            metrics.execution_plan["component_metrics"] = {
                "vector": {
                    "duration_ms": vector_metrics.duration_ms,
                    "result_count": vector_metrics.result_count,
                    "scan_count": vector_metrics.scan_count
                },
                "graph": {
                    "duration_ms": graph_metrics.duration_ms,
                    "result_count": graph_metrics.result_count,
                    "scan_count": graph_metrics.scan_count
                }
            }

        except Exception as e:
            logger.error(f"Error executing hybrid query {query_id}: {str(e)}")
            metrics.complete(
                result_count=0,
                scan_count=0,
                error=str(e)
            )
            raise
        finally:
            # Record the metrics
            self.query_optimizer.stats.record_query(metrics)

        return merged_result, metrics


# Factory function to create a complete optimizer stack
def create_query_optimizer(max_cache_size: int = 100,
                         collect_statistics: bool = True,
                         optimize_vectors: bool = True,
                         optimize_graphs: bool = True,
                         optimize_hybrid: bool = True) -> Dict[str, Any]:
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
    # Create base components
    stats_collector = QueryStatsCollector() if collect_statistics else None
    query_cache = LRUQueryCache(max_size=max_cache_size)
    index_registry = IndexRegistry()

    # Create base optimizer
    query_optimizer = QueryOptimizer(
        stats_collector=stats_collector,
        query_cache=query_cache,
        index_registry=index_registry
    )

    # Create specialized optimizers
    optimizers = {"base": query_optimizer}

    if optimize_vectors:
        vector_optimizer = VectorIndexOptimizer(query_optimizer)
        optimizers["vector"] = vector_optimizer

    if optimize_graphs:
        graph_optimizer = KnowledgeGraphQueryOptimizer(query_optimizer)
        optimizers["graph"] = graph_optimizer

    if optimize_hybrid and optimize_vectors and optimize_graphs:
        hybrid_optimizer = HybridQueryOptimizer(optimizers["vector"], optimizers["graph"])
        optimizers["hybrid"] = hybrid_optimizer

    return optimizers
