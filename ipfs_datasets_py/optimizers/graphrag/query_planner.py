"""Core query planning and execution optimizer for GraphRAG."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

# Optional dependencies with graceful fallbacks.
try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

    class _MockNumpy:
        @staticmethod
        def std(x):
            if not x:
                return 0
            mean_val = sum(x) / len(x)
            variance = sum((v - mean_val) ** 2 for v in x) / len(x)
            return variance ** 0.5

    np = _MockNumpy()

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False

    class _MockPsutil:
        @staticmethod
        def virtual_memory():
            return type('Memory', (), {'percent': 50, 'available': 1000000000})()

        class Process:
            def memory_info(self):
                return type('MemInfo', (), {'rss': 0, 'vms': 0})()

    psutil = _MockPsutil()

from ipfs_datasets_py.optimizers.graphrag.learning_adapter import (
    apply_learning_hook,
    check_learning_cycle,
    increment_failure_counter,
)
from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
from ipfs_datasets_py.optimizers.graphrag.query_visualizer import QueryVisualizer
from ipfs_datasets_py.optimizers.graphrag.query_stats import GraphRAGQueryStats


class GraphRAGQueryOptimizer:
    """
    Optimizes query execution for GraphRAG operations.
    
    Features:
    - Query caching for frequently executed queries
    - Adaptive parameter adjustment based on query statistics
    - Query plan generation for complex GraphRAG operations
    """
    
    def __init__(
        self, 
        query_stats: Optional[GraphRAGQueryStats] = None,
        vector_weight: float = 0.7,
        graph_weight: float = 0.3,
        cache_enabled: bool = True,
        cache_ttl: float = 300.0,
        cache_size_limit: int = 100
    ):
        """
        Initialize the query optimizer.
        
        Args:
            query_stats (GraphRAGQueryStats, optional): Query statistics tracker
            vector_weight (float): Weight for vector similarity in hybrid queries
            graph_weight (float): Weight for graph structure in hybrid queries
            cache_enabled (bool): Whether to enable query caching
            cache_ttl (float): Time-to-live for cached results in seconds
            cache_size_limit (int): Maximum number of cached queries
        """
        self.query_stats = query_stats or GraphRAGQueryStats()
        self.vector_weight = vector_weight
        self.graph_weight = graph_weight
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self.cache_size_limit = cache_size_limit
        
        # Query cache
        self.query_cache: Dict[str, Tuple[Any, float]] = {}  # {query_key: (result, timestamp)}
        
    def optimize_query(
        self, 
        query_vector: Any,
        max_vector_results: int = 5,
        max_traversal_depth: int = 2,
        edge_types: Optional[List[str]] = None,
        min_similarity: float = 0.5
    ) -> Dict[str, Any]:
        """
        Generate an optimized query plan based on statistics and preferences.
        
        Args:
            query_vector (np.ndarray): Query vector
            max_vector_results (int): Maximum number of initial vector similarity matches
            max_traversal_depth (int): Maximum traversal depth from each similarity match
            edge_types (List[str], optional): Types of edges to follow
            min_similarity (float): Minimum similarity score for initial vector matches
            
        Returns:
            Dict: Optimized query parameters
        """
        # Start with the provided parameters
        optimized_params = {
            "max_vector_results": max_vector_results,
            "max_traversal_depth": max_traversal_depth,
            "edge_types": edge_types,
            "min_similarity": min_similarity
        }
        
        # If we have enough statistics, make adjustments based on performance
        if self.query_stats.query_count >= 10:
            # 1. Adjust max_vector_results based on query times
            avg_time = self.query_stats.avg_query_time
            if avg_time > 1.0 and max_vector_results > 3:
                # If queries are slow, reduce the number of initial matches
                optimized_params["max_vector_results"] = max(3, max_vector_results - 2)
            elif avg_time < 0.1 and max_vector_results < 10:
                # If queries are fast, we can increase matches
                optimized_params["max_vector_results"] = min(10, max_vector_results + 2)
                
            # 2. Adjust traversal depth based on query patterns
            common_patterns = self.query_stats.get_common_patterns()
            if common_patterns:
                # Find the most common traversal depth
                depths = [pattern.get("max_traversal_depth", 2) for pattern, _ in common_patterns]
                common_depth = max(set(depths), key=depths.count)
                optimized_params["max_traversal_depth"] = common_depth
                
            # 3. Adjust similarity threshold based on cache hit rate
            if self.query_stats.cache_hit_rate < 0.3:
                # Low cache hit rate might indicate too strict filtering
                optimized_params["min_similarity"] = max(0.3, min_similarity - 0.1)
        
        # Record the query pattern
        self.query_stats.record_query_pattern(optimized_params)
        
        # Return the optimized parameters
        return {
            "params": optimized_params,
            "weights": {
                "vector": self.vector_weight,
                "graph": self.graph_weight
            }
        }
        
    def get_query_key(
        self, 
        query_vector: Any,
        max_vector_results: int = 5,
        max_traversal_depth: int = 2,
        edge_types: Optional[List[str]] = None,
        min_similarity: float = 0.5
    ) -> str:
        """
        Generate a unique key for a query for caching purposes.
        
        Args:
            query_vector (np.ndarray): Query vector
            max_vector_results (int): Maximum number of initial vector similarity matches
            max_traversal_depth (int): Maximum traversal depth
            edge_types (List[str], optional): Types of edges to follow
            min_similarity (float): Minimum similarity score
            
        Returns:
            str: Query key for cache lookup
        """
        try:
            # Normalize query vector with more consistent and unique representation
            if query_vector is None:
                vector_hash = "none_vector"
            elif hasattr(query_vector, 'tolist'):
                # Get a stable representation of the vector
                # Use a more comprehensive representation for better uniqueness
                if len(query_vector) > 0:
                    # Compute average, min, max, and other statistics for a more unique fingerprint
                    # This captures essence of the entire vector without using all elements
                    vector_avg = float(np.mean(query_vector))
                    vector_min = float(np.min(query_vector))
                    vector_max = float(np.max(query_vector))
                    vector_stddev = float(np.std(query_vector))
                    # Also include first, middle and last elements for more uniqueness
                    first_elements = query_vector[:min(3, len(query_vector))].tolist()
                    mid_idx = len(query_vector) // 2
                    mid_elements = query_vector[mid_idx:mid_idx+2].tolist() if mid_idx+2 <= len(query_vector) else []
                    last_elements = query_vector[max(0, len(query_vector)-3):].tolist()
                    # Create a stable hash from these statistics
                    vector_hash = f"v_len{len(query_vector)}_avg{vector_avg:.6f}_min{vector_min:.6f}_max{vector_max:.6f}_std{vector_stddev:.6f}_f{first_elements}_m{mid_elements}_l{last_elements}"
                else:
                    vector_hash = "v_empty"
            else:
                # Fallback for non-numpy vector types - use more of the string for better uniqueness
                vector_hash = f"s_{hash(str(query_vector))}"  # Use full hash
            
            # Normalize edge types for consistency
            if edge_types is None:
                normalized_edge_types = None
            elif isinstance(edge_types, (list, tuple)):
                normalized_edge_types = sorted(str(edge) for edge in edge_types)
            else:
                normalized_edge_types = str(edge_types)
            
            # Create a dictionary of query parameters with normalized values
            query_params = {
                "vector": vector_hash,
                "max_vector_results": int(max_vector_results),
                "max_traversal_depth": int(max_traversal_depth),
                "edge_types": normalized_edge_types,
                "min_similarity": float(min_similarity)
            }
            
            # Convert to string and hash for cache key
            # Use a more stable string representation for consistent keys across runs
            params_str = str(sorted([(k, str(v)) for k, v in query_params.items()]))
            return hashlib.sha256(params_str.encode()).hexdigest()
            
        except Exception as e:
            # If anything goes wrong, create a more robust fallback key with all available parameters
            # Include as many parameters as possible to avoid incorrect cache hits
            fallback_parts = [
                f"vctr_res{max_vector_results}",
                f"trav_depth{max_traversal_depth}",
                f"min_sim{min_similarity}"
            ]
            
            # Add edge types if available
            if edge_types is not None:
                try:
                    # Sort and join edge types for consistency
                    edge_str = "_".join(sorted(str(edge) for edge in edge_types))
                    fallback_parts.append(f"edges{edge_str}")
                except Exception:
                    fallback_parts.append("edges_error")
            
            # Add vector summary if available
            if query_vector is not None:
                try:
                    # Try to get some vector characteristics even if full processing failed
                    if hasattr(query_vector, 'shape'):
                        fallback_parts.append(f"vshape{query_vector.shape}")
                    if hasattr(query_vector, '__len__'):
                        fallback_parts.append(f"vlen{len(query_vector)}")
                except Exception:
                    fallback_parts.append("vector_error")
            
            fallback_key = "fallback_" + "_".join(fallback_parts)
            
            # Log the error with more details
            if hasattr(self, 'logger'):
                self.logger.warning(f"Error generating cache key, using fallback: {str(e)}\nFallback key: {fallback_key}")
            elif hasattr(self, 'log_error'):
                self.log_error(f"Cache key generation error: {str(e)}")
                
            return hashlib.sha256(fallback_key.encode()).hexdigest()
        
    def is_in_cache(self, query_key: str) -> bool:
        """
        Check if a query is in the cache and not expired.
        
        Args:
            query_key (str): Query key
            
        Returns:
            bool: Whether the query is in cache
        """
        try:
            # Basic validation
            if not self.cache_enabled:
                return False
                
            if query_key is None:
                return False
                
            if not hasattr(self, 'query_cache') or self.query_cache is None:
                return False
                
            # Check if the query exists in cache
            if query_key not in self.query_cache:
                return False
                
            # Check if the cached result has expired
            entry = self.query_cache.get(query_key)
            if entry is None:
                return False
                
            # Validate entry structure
            if not isinstance(entry, tuple) or len(entry) != 2:
                # Invalid cache entry, remove it
                if query_key in self.query_cache:
                    del self.query_cache[query_key]
                return False
                
            _, timestamp = entry
            
            # Verify timestamp is valid
            if not isinstance(timestamp, (int, float)):
                if query_key in self.query_cache:
                    del self.query_cache[query_key]
                return False
                
            # Check expiration
            if time.time() - timestamp > self.cache_ttl:
                # Remove expired entry
                if query_key in self.query_cache:
                    del self.query_cache[query_key]
                return False
                
            return True
            
        except Exception as e:
            # If any error occurs, consider it a cache miss, but provide better diagnostics
            error_msg = f"Error checking cache: {str(e)}"
            if hasattr(self, 'logger'):
                self.logger.warning(error_msg)
            elif hasattr(self, 'log_error'):
                self.log_error(error_msg, "cache")
                
            # During development or debugging, uncomment to raise the exception:
            # raise e
            
            return False
        
    def get_from_cache(self, query_key: str) -> Any:
        """
        Get a query result from cache.
        
        Args:
            query_key (str): Query key
            
        Returns:
            Any: Cached query result
            
        Raises:
            KeyError: If the query is not in cache
        """
        try:
            # Verify the query is in cache
            if not self.is_in_cache(query_key):
                raise KeyError(f"Query {query_key} not in cache or expired")
                
            # Get the cached result
            cache_entry = self.query_cache.get(query_key)
            if cache_entry is None:
                raise KeyError(f"Query {query_key} missing from cache (race condition)")
                
            # Validate cache entry structure
            if not isinstance(cache_entry, tuple) or len(cache_entry) != 2:
                raise ValueError(f"Invalid cache entry format for query {query_key}")
                
            result, _ = cache_entry
            
            # Record cache hit and ensure proper stats tracking
            if hasattr(self, 'query_stats') and self.query_stats is not None:
                try:
                    # Record cache hit - this is critical for tracking
                    self.query_stats.record_cache_hit()
                    
                    # Do NOT record a query time for cached results to avoid
                    # inflating the query count incorrectly
                    # This was causing incorrect query counts in statistical learning
                except Exception as stats_error:
                    # Log error but continue - stats are non-critical
                    if hasattr(self, 'logger'):
                        self.logger.warning(f"Error recording cache hit stats: {str(stats_error)}")
            
            # Return cached result
            return result
            
        except (KeyError, ValueError) as e:
            # Improve error reporting before re-raising expected exceptions
            error_msg = f"Cache retrieval error ({e.__class__.__name__}) for query {query_key}: {str(e)}"
            if hasattr(self, 'logger'):
                self.logger.debug(error_msg)  # Use debug level for expected errors
            elif hasattr(self, 'log_error'):
                self.log_error(error_msg, "cache", level="debug")
            raise  # Re-raise the original exception without modification
            
        except Exception as e:
            # For unexpected errors, provide more context and better diagnostics
            error_msg = f"Unexpected error retrieving from cache: {str(e)}, query_key={query_key}"
            if hasattr(self, 'logger'):
                self.logger.error(error_msg)
            elif hasattr(self, 'log_error'):
                self.log_error(error_msg, "cache", level="error")
                
            # For debugging or development, you can add more diagnostics:
            # import traceback
            # if hasattr(self, 'logger'):
            #     self.logger.error(f"Cache error traceback: {traceback.format_exc()}")
                
            # Convert unexpected errors to KeyError with meaningful message
            raise KeyError(error_msg)
        
    def add_to_cache(self, query_key: str, result: Any) -> None:
        """
        Add a query result to the cache.
        
        Args:
            query_key (str): Query key
            result (Any): Query result to cache
        """
        try:
            # Validate inputs and cache status
            if not self.cache_enabled:
                return
                
            if query_key is None:
                if hasattr(self, 'logger'):
                    self.logger.warning("Cannot add None key to cache")
                return
                
            if not hasattr(self, 'query_cache') or self.query_cache is None:
                # Initialize the cache if it doesn't exist
                self.query_cache = {}
                if hasattr(self, 'logger'):
                    self.logger.info("Initializing cache")
            
            # Check if result is valid
            if result is None:
                if hasattr(self, 'logger'):
                    self.logger.warning(f"Not caching None result for key {query_key}")
                return
                
            # Check if result might cause serialization problems with numpy arrays
            try:
                # Process result to ensure it's cache-safe
                clean_result = self._sanitize_for_cache(result)
                
                # Verify we can get a string representation
                result_str = str(clean_result)[:50]  # Truncate for reasonable log message size
            except Exception as serr:
                # If we can't process the result safely, don't cache it
                if hasattr(self, 'logger'):
                    self.logger.warning(f"Cannot serialize result for key {query_key}: {str(serr)}")
                return
            
            # Add to cache with current timestamp
            timestamp = time.time()
            self.query_cache[query_key] = (clean_result, timestamp)
            
            # Log cache update if logger available
            if hasattr(self, 'logger') and hasattr(self.logger, 'debug'):
                cache_size = len(self.query_cache) if self.query_cache else 0
                self.logger.debug(f"Added to cache: {query_key[:10]}... (cache size: {cache_size})")
            
            # Enforce cache size limit
            if len(self.query_cache) > self.cache_size_limit:
                try:
                    # Find oldest entry (safeguard against any potential errors)
                    oldest_timestamp = float('inf')
                    oldest_key = None
                    
                    for k, v in self.query_cache.items():
                        if isinstance(v, tuple) and len(v) == 2:
                            entry_timestamp = v[1]
                            if isinstance(entry_timestamp, (int, float)) and entry_timestamp < oldest_timestamp:
                                oldest_timestamp = entry_timestamp
                                oldest_key = k
                    
                    # Remove oldest entry if found
                    if oldest_key is not None:
                        del self.query_cache[oldest_key]
                        if hasattr(self, 'logger') and hasattr(self.logger, 'debug'):
                            self.logger.debug(f"Removed oldest cache entry: {oldest_key[:10]}...")
                    else:
                        # Fallback: remove a random entry if we couldn't determine the oldest
                        if self.query_cache:
                            random_key = next(iter(self.query_cache))
                            del self.query_cache[random_key]
                            if hasattr(self, 'logger'):
                                self.logger.warning(f"Removed random cache entry (couldn't determine oldest)")
                                
                except Exception as e:
                    # If cache management fails, log and continue
                    if hasattr(self, 'logger'):
                        self.logger.warning(f"Error managing cache size: {str(e)}")
                    
        except Exception as e:
            # Log error with better diagnostics but don't fail the operation for cache issues
            error_msg = f"Error adding to cache: {str(e)}, key={query_key}"
            if hasattr(self, 'logger'):
                self.logger.warning(error_msg)
            elif hasattr(self, 'log_error'):
                self.log_error(error_msg, "cache")
                
            # For debugging or development, consider uncommenting:
            # import traceback
            # if hasattr(self, 'logger'):
            #     self.logger.error(f"Cache error traceback: {traceback.format_exc()}")
                
    def _sanitize_for_cache(self, result: Any) -> Any:
        """
        Sanitize result for cache storage, handling numpy arrays and other problematic types.
        Uses more robust handling of nested structures and numpy types.
        
        Args:
            result: The result to sanitize
            
        Returns:
            A cache-safe version of the result
        """
        # First try to import numpy, but don't fail if not available
        try:
            import numpy as np
            NUMPY_AVAILABLE = True
        except ImportError:
            NUMPY_AVAILABLE = False
            
        # Handle None case first
        if result is None:
            return None
            
        # For dictionaries, recursively process all values
        if isinstance(result, dict):
            return {k: self._sanitize_for_cache(v) for k, v in result.items()}
            
        # For lists, recursively process all items
        if isinstance(result, list):
            return [self._sanitize_for_cache(item) for item in result]
            
        # For tuples, convert to list and recursively process
        if isinstance(result, tuple):
            return tuple(self._sanitize_for_cache(item) for item in result)
            
        # For sets, convert to list and recursively process
        if isinstance(result, set):
            return [self._sanitize_for_cache(item) for item in result]
            
        # If numpy is available, handle numpy types
        if NUMPY_AVAILABLE:
            import numpy as np
            
            # Handle numpy array with improved error handling and safety
            if isinstance(result, np.ndarray):
                try:
                    # For small arrays, convert to list directly
                    if result.size <= 10000:  # Only convert small arrays
                        return [self._sanitize_for_cache(x) for x in result.tolist()]
                    else:
                        # For large arrays, store key statistics instead of the full data
                        # This prevents memory issues and serialization failures
                        stats = {
                            "type": "numpy_array_summary",
                            "shape": result.shape,
                            "dtype": str(result.dtype),
                            "mean": float(np.mean(result)) if result.dtype.kind in 'iufc' else None,
                            "min": float(np.min(result)) if result.dtype.kind in 'iufc' else None,
                            "max": float(np.max(result)) if result.dtype.kind in 'iufc' else None,
                            "first_5": result.flatten()[:5].tolist() if result.size > 0 else [],
                            "last_5": result.flatten()[-5:].tolist() if result.size > 0 else []
                        }
                        return stats
                except Exception as e:
                    # Provide better fallback with error context
                    try:
                        return {
                            "type": "numpy_array_error",
                            "shape": result.shape if hasattr(result, 'shape') else None,
                            "dtype": str(result.dtype) if hasattr(result, 'dtype') else None,
                            "error": str(e),
                            "stringified": str(result)[:1000]  # Truncate to avoid massive strings
                        }
                    except:
                        return f"<NumPy array that could not be serialized>"
            
            # Handle numpy scalar types
            if isinstance(result, np.integer):
                return int(result)
            elif isinstance(result, np.floating):
                return float(result)
            elif isinstance(result, np.bool_):
                return bool(result)
            elif isinstance(result, np.str_):
                return str(result)
            elif isinstance(result, (np.bytes_, np.void)):
                try:
                    return result.item().decode('utf-8', errors='replace')
                except:
                    return str(result)
            elif isinstance(result, (np.datetime64, np.timedelta64)):
                return str(result)
            elif isinstance(result, np.complex128):
                return {"real": float(result.real), "imag": float(result.imag)}
            
            # Handle other numpy types with item method
            elif hasattr(result, 'item') and callable(result.item):
                try:
                    return result.item()
                except:
                    return str(result)
                    
        # For primitive types, return as is
        if isinstance(result, (int, float, str, bool)):
            return result
            
        # For complex objects, attempt to convert to string
        try:
            return str(result)
        except:
            # If all else fails, use a placeholder to avoid cache failures
            return f"<Uncacheable object of type {type(result).__name__}>"
            
    def clear_cache(self) -> None:
        """Clear the query cache."""
        self.query_cache.clear()
        
    def generate_query_plan(
        self,
        query_vector: Any,
        max_vector_results: int = 5,
        max_traversal_depth: int = 2,
        edge_types: Optional[List[str]] = None,
        min_similarity: float = 0.5
    ) -> Dict[str, Any]:
        """
        Generate a query plan for GraphRAG operations.
        
        Args:
            query_vector (np.ndarray): Query vector
            max_vector_results (int): Maximum number of initial vector similarity matches
            max_traversal_depth (int): Maximum traversal depth
            edge_types (List[str], optional): Types of edges to follow
            min_similarity (float): Minimum similarity score
            
        Returns:
            Dict: Query plan with execution strategy
        """
        # Get optimized query parameters
        optimized = self.optimize_query(
            query_vector,
            max_vector_results,
            max_traversal_depth,
            edge_types,
            min_similarity
        )
        
        params = optimized["params"]
        weights = optimized["weights"]
        
        # Generate the query plan steps
        plan = {
            "steps": [
                {
                    "name": "vector_similarity_search",
                    "description": "Find initial matches by vector similarity",
                    "params": {
                        "query_vector": query_vector,
                        "top_k": params["max_vector_results"],
                        "min_score": params["min_similarity"]
                    }
                },
                {
                    "name": "graph_traversal",
                    "description": "Expand matches through graph traversal",
                    "params": {
                        "max_depth": params["max_traversal_depth"],
                        "edge_types": params["edge_types"] or []
                    }
                },
                {
                    "name": "result_ranking",
                    "description": "Rank combined results",
                    "params": {
                        "vector_weight": weights["vector"],
                        "graph_weight": weights["graph"]
                    }
                }
            ],
            "caching": {
                "enabled": self.cache_enabled,
                "key": self.get_query_key(
                    query_vector,
                    params["max_vector_results"],
                    params["max_traversal_depth"],
                    params["edge_types"],
                    params["min_similarity"]
                )
            },
            "statistics": {
                "avg_query_time": self.query_stats.avg_query_time,
                "cache_hit_rate": self.query_stats.cache_hit_rate
            }
        }
        
        return plan
        
    def execute_query(
        self,
        graph_rag_processor: Any,
        query_vector: Any,
        max_vector_results: int = 5,
        max_traversal_depth: int = 2,
        edge_types: Optional[List[str]] = None,
        min_similarity: float = 0.5,
        skip_cache: bool = False
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Execute a GraphRAG query with optimizations.
        
        Args:
            graph_rag_processor: A GraphRAG processor implementation
            query_vector (np.ndarray): Query vector
            max_vector_results (int): Maximum number of initial vector similarity matches
            max_traversal_depth (int): Maximum traversal depth
            edge_types (List[str], optional): Types of edges to follow
            min_similarity (float): Minimum similarity score
            skip_cache (bool): Whether to skip cache lookup
            
        Returns:
            Tuple[List[Dict[str, Any]], Dict[str, Any]]: (Results, execution_info)
        """
        # Generate query plan
        plan = self.generate_query_plan(
            query_vector,
            max_vector_results,
            max_traversal_depth,
            edge_types,
            min_similarity
        )
        
        # Check cache if enabled and not skipped
        if self.cache_enabled and not skip_cache:
            cache_key = plan["caching"]["key"]
            if self.is_in_cache(cache_key):
                cached_result = self.get_from_cache(cache_key)
                return cached_result, {"from_cache": True, "plan": plan}
        
        # Start timing query execution
        start_time = time.time()
        
        # Execute query using the graph_rag_processor
        # First step: Vector similarity search
        vector_step = plan["steps"][0]["params"]
        vector_results = graph_rag_processor.search_by_vector(
            vector_step["query_vector"],
            top_k=vector_step["top_k"],
            min_score=vector_step["min_score"]
        )
        
        # Second step: Graph traversal from vector results
        traversal_step = plan["steps"][1]["params"]
        graph_results = graph_rag_processor.expand_by_graph(
            vector_results,
            max_depth=traversal_step["max_depth"],
            edge_types=traversal_step["edge_types"]
        )
        
        # Third step: Result ranking
        ranking_step = plan["steps"][2]["params"]
        combined_results = graph_rag_processor.rank_results(
            graph_results,
            vector_weight=ranking_step["vector_weight"],
            graph_weight=ranking_step["graph_weight"]
        )
        
        # Record execution time
        execution_time = time.time() - start_time
        self.query_stats.record_query_time(execution_time)
        
        # Cache result if enabled
        if self.cache_enabled:
            self.add_to_cache(plan["caching"]["key"], combined_results)
        
        # Return results and execution info
        execution_info = {
            "from_cache": False,
            "execution_time": execution_time,
            "plan": plan
        }
        
        return combined_results, execution_info
