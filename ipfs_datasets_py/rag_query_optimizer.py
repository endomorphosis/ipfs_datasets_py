"""
Query Optimization Module for GraphRAG operations.

This module provides a comprehensive framework for optimizing GraphRAG (Graph Retrieval
Augmented Generation) queries across different knowledge graph types. The optimization
strategies are tailored to the specific characteristics of Wikipedia-derived knowledge
graphs, IPLD-based knowledge graphs, and mixed environments containing both types.

Key features:
- Query statistics collection and analysis for adaptive optimization
- Intelligent caching of frequently executed queries
- Query plan generation and execution with content-type awareness
- Vector index partitioning for improved search performance across large datasets
- Specialized optimizations for Wikipedia-derived knowledge graphs
- IPLD-specific optimizations leveraging content-addressed data structures
- Cross-document reasoning query planning with entity-based traversal
- Content-addressed graph traversal strategies for IPLD DAGs
- Multi-graph query optimization for mixed environments
- Performance analysis and recommendations
- Adaptive parameter tuning based on query patterns
- Query rewriting for improved traversal paths
- Advanced caching mechanisms for frequently accessed paths
- Hierarchical traversal planning with hop-limited paths
- Query cost estimation and budget-aware execution

Advanced Optimization Components:
- QueryRewriter: Analyzes and rewrites queries for better performance using:
  - Predicate pushdown for early filtering
  - Join reordering based on edge selectivity
  - Traversal path optimization based on graph characteristics
  - Pattern-specific optimizations for common query types
  - Domain-specific query transformations

- QueryBudgetManager: Manages query execution resources through:
  - Dynamic resource allocation based on query priority and complexity
  - Early stopping based on result quality and diminishing returns
  - Adaptive computation budgeting based on query history
  - Progressive query expansion driven by initial results
  - Timeout management and cost estimation

- UnifiedGraphRAGQueryOptimizer: Combines optimization strategies for different graph types:
  - Auto-detection of graph type from query parameters
  - Wikipedia-specific and IPLD-specific optimizations
  - Cross-graph query planning for heterogeneous environments
  - Comprehensive performance analysis and recommendation generation
  - Integration with advanced rewriting and budget management

This module integrates with the llm_graphrag module to provide optimized graph
traversal strategies that enhance cross-document reasoning capabilities with LLMs.
"""

import time
import hashlib
import json
import numpy as np
import re
from typing import Dict, List, Any, Optional, Tuple, Callable, Union, Set, TYPE_CHECKING
from collections import defaultdict

# Import for Wikipedia-specific optimizations
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer

# Avoid circular imports with conditional imports
if TYPE_CHECKING:
    from ipfs_datasets_py.llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer

class GraphRAGQueryStats:
    """
    Collects and analyzes query statistics for optimization purposes.
    
    This class tracks metrics such as query execution time, cache hit rate,
    and query patterns to inform the query optimizer's decisions.
    """
    
    def __init__(self):
        """Initialize the query statistics tracker."""
        self.query_count = 0
        self.cache_hits = 0
        self.total_query_time = 0.0
        self.query_times = []
        self.query_patterns = defaultdict(int)
        self.query_timestamps = []
        
    @property
    def avg_query_time(self) -> float:
        """Calculate the average query execution time."""
        if self.query_count == 0:
            return 0.0
        return self.total_query_time / self.query_count
        
    @property
    def cache_hit_rate(self) -> float:
        """Calculate the cache hit rate."""
        if self.query_count == 0:
            return 0.0
        return self.cache_hits / self.query_count
        
    def record_query_time(self, execution_time: float) -> None:
        """
        Record the execution time of a query.
        
        Args:
            execution_time (float): Query execution time in seconds
        """
        self.query_count += 1
        self.total_query_time += execution_time
        self.query_times.append(execution_time)
        self.query_timestamps.append(time.time())
        
    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.cache_hits += 1
        
    def record_query_pattern(self, pattern: Dict[str, Any]) -> None:
        """
        Record a query pattern for analysis.
        
        Args:
            pattern (Dict): Query pattern representation
        """
        # Convert the pattern to a hashable representation
        pattern_key = json.dumps(pattern, sort_keys=True)
        self.query_patterns[pattern_key] += 1
        
    def get_common_patterns(self, top_n: int = 5) -> List[Tuple[Dict[str, Any], int]]:
        """
        Get the most common query patterns.
        
        Args:
            top_n (int): Number of patterns to return
            
        Returns:
            List[Tuple[Dict, int]]: List of (pattern, count) tuples
        """
        # Sort patterns by frequency
        sorted_patterns = sorted(self.query_patterns.items(), key=lambda x: x[1], reverse=True)
        
        # Convert pattern keys back to dictionaries
        return [(json.loads(pattern), count) for pattern, count in sorted_patterns[:top_n]]
        
    def get_recent_query_times(self, window_seconds: float = 300.0) -> List[float]:
        """
        Get query times from the recent time window.
        
        Args:
            window_seconds (float): Time window in seconds
            
        Returns:
            List[float]: List of query execution times in the window
        """
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # Filter query times by timestamp
        recent_times = []
        for i, timestamp in enumerate(self.query_timestamps):
            if timestamp >= cutoff_time:
                recent_times.append(self.query_times[i])
                
        return recent_times
        
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get a summary of query performance statistics.
        
        Returns:
            Dict: Summary statistics
        """
        recent_times = self.get_recent_query_times()
        
        return {
            "query_count": self.query_count,
            "cache_hit_rate": self.cache_hit_rate,
            "avg_query_time": self.avg_query_time,
            "min_query_time": min(self.query_times) if self.query_times else 0.0,
            "max_query_time": max(self.query_times) if self.query_times else 0.0,
            "recent_avg_time": sum(recent_times) / len(recent_times) if recent_times else 0.0,
            "common_patterns": self.get_common_patterns()
        }
        
    def reset(self) -> None:
        """Reset all statistics."""
        self.query_count = 0
        self.cache_hits = 0
        self.total_query_time = 0.0
        self.query_times = []
        self.query_patterns = defaultdict(int)
        self.query_timestamps = []


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
        query_vector: np.ndarray,
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
        query_vector: np.ndarray,
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
        # Create a dictionary of query parameters
        query_params = {
            "vector": query_vector.tobytes().hex()[:100],  # Truncate for reasonable key size
            "max_vector_results": max_vector_results,
            "max_traversal_depth": max_traversal_depth,
            "edge_types": edge_types,
            "min_similarity": min_similarity
        }
        
        # Convert to string and hash for cache key
        params_str = json.dumps(query_params, sort_keys=True)
        return hashlib.sha256(params_str.encode()).hexdigest()
        
    def is_in_cache(self, query_key: str) -> bool:
        """
        Check if a query is in the cache and not expired.
        
        Args:
            query_key (str): Query key
            
        Returns:
            bool: Whether the query is in cache
        """
        if not self.cache_enabled or query_key not in self.query_cache:
            return False
            
        # Check if the cached result has expired
        _, timestamp = self.query_cache[query_key]
        if time.time() - timestamp > self.cache_ttl:
            # Remove expired entry
            del self.query_cache[query_key]
            return False
            
        return True
        
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
        if not self.is_in_cache(query_key):
            raise KeyError(f"Query {query_key} not in cache or expired")
            
        # Record cache hit
        self.query_stats.record_cache_hit()
        
        # Return cached result
        result, _ = self.query_cache[query_key]
        return result
        
    def add_to_cache(self, query_key: str, result: Any) -> None:
        """
        Add a query result to the cache.
        
        Args:
            query_key (str): Query key
            result (Any): Query result to cache
        """
        if not self.cache_enabled:
            return
            
        # Add to cache with current timestamp
        self.query_cache[query_key] = (result, time.time())
        
        # Enforce cache size limit
        if len(self.query_cache) > self.cache_size_limit:
            # Remove oldest entry
            oldest_key = min(self.query_cache, key=lambda k: self.query_cache[k][1])
            del self.query_cache[oldest_key]
            
    def clear_cache(self) -> None:
        """Clear the query cache."""
        self.query_cache.clear()
        
    def generate_query_plan(
        self,
        query_vector: np.ndarray,
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
        query_vector: np.ndarray,
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


class QueryRewriter:
    """
    Analyzes and rewrites queries for better performance.
    
    Features:
    - Predicate pushdown for early filtering
    - Join reordering based on edge selectivity
    - Traversal path optimization based on graph characteristics
    - Pattern-specific optimizations for common query types
    - Domain-specific query transformations
    """
    
    def __init__(self):
        """Initialize the query rewriter."""
        self.optimization_patterns = [
            self._apply_predicate_pushdown,
            self._reorder_joins_by_selectivity,
            self._optimize_traversal_path,
            self._apply_pattern_specific_optimizations,
            self._apply_domain_optimizations
        ]
        self.query_stats = {}
        
    def rewrite_query(self, query: Dict[str, Any], graph_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Rewrite a query for better performance.
        
        Args:
            query (Dict): Original query
            graph_info (Dict, optional): Information about the graph structure
            
        Returns:
            Dict: Rewritten query
        """
        # Start with a copy of the original query
        rewritten_query = query.copy()
        
        # Apply optimization patterns
        for optimization_func in self.optimization_patterns:
            rewritten_query = optimization_func(rewritten_query, graph_info)
            
        # Return the rewritten query
        return rewritten_query
    
    def _apply_predicate_pushdown(self, query: Dict[str, Any], graph_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Applies predicate pushdown to filter early in the query.
        
        Args:
            query (Dict): Query to optimize
            graph_info (Dict, optional): Graph structure information
            
        Returns:
            Dict: Query with predicates pushed down
        """
        # Clone the query
        result = query.copy()
        
        # If the query has a similarity threshold, apply it during vector search
        if "min_similarity" in result and "vector_params" in result:
            result["vector_params"]["min_score"] = result.pop("min_similarity")
            
        # If there are entity type filters, push those to initial entity selection
        if "entity_filters" in result and "entity_types" in result.get("entity_filters", {}):
            entity_types = result["entity_filters"]["entity_types"]
            # Move entity type filtering to vector search step
            if "vector_params" in result and entity_types:
                result["vector_params"]["entity_types"] = entity_types
                
        return result
    
    def _reorder_joins_by_selectivity(self, query: Dict[str, Any], graph_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Reorders graph traversal joins based on edge selectivity.
        
        Args:
            query (Dict): Query to optimize
            graph_info (Dict, optional): Graph structure information
            
        Returns:
            Dict: Query with reordered joins
        """
        result = query.copy()
        
        # If traversal specified and graph_info available, reorder by selectivity
        if "traversal" in result and graph_info and "edge_selectivity" in graph_info:
            edge_types = result["traversal"].get("edge_types", [])
            if edge_types:
                # Sort edge types by selectivity (most selective first)
                selectivity = graph_info["edge_selectivity"]
                edge_types.sort(key=lambda et: selectivity.get(et, 0.5))
                result["traversal"]["edge_types"] = edge_types
                
        return result
    
    def _optimize_traversal_path(self, query: Dict[str, Any], graph_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Optimizes graph traversal paths based on graph characteristics.
        
        Args:
            query (Dict): Query to optimize
            graph_info (Dict, optional): Graph structure information
            
        Returns:
            Dict: Query with optimized traversal paths
        """
        result = query.copy()
        
        # If max_depth is high, consider breadth-limited traversal strategy
        if "traversal" in result and result["traversal"].get("max_depth", 0) > 2:
            result["traversal"]["strategy"] = "breadth_limited"
            result["traversal"]["max_breadth_per_level"] = 5  # Limit nodes expanded per level
        
        # For dense graphs, use sampling strategy to avoid combinatorial explosion
        if graph_info and graph_info.get("graph_density", 0) > 0.7:
            if "traversal" in result:
                result["traversal"]["strategy"] = "sampling"
                result["traversal"]["sample_ratio"] = 0.3  # Sample 30% of edges at each step
                
        return result
    
    def _apply_pattern_specific_optimizations(self, query: Dict[str, Any], graph_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Applies optimizations specific to common query patterns.
        
        Args:
            query (Dict): Query to optimize
            graph_info (Dict, optional): Graph structure information
            
        Returns:
            Dict: Query with pattern-specific optimizations
        """
        result = query.copy()
        
        # Detect query pattern type
        pattern = self._detect_query_pattern(result)
        
        # Apply optimizations based on pattern
        if pattern == "entity_lookup":
            # Direct entity lookup - skip vector search if possible
            if "entity_id" in result:
                result["skip_vector_search"] = True
        elif pattern == "relation_centric":
            # Relation-centric query - prioritize relationship expansion
            if "traversal" in result:
                result["traversal"]["prioritize_relationships"] = True
        elif pattern == "fact_verification":
            # Fact verification - use direct path finding instead of exploration
            if "traversal" in result:
                result["traversal"]["strategy"] = "path_finding"
                result["traversal"]["find_shortest_path"] = True
                
        return result
    
    def _apply_domain_optimizations(self, query: Dict[str, Any], graph_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Applies domain-specific query transformations.
        
        Args:
            query (Dict): Query to optimize
            graph_info (Dict, optional): Graph structure information
            
        Returns:
            Dict: Query with domain-specific optimizations
        """
        result = query.copy()
        
        # Detect if query is for wikipedia-derived graph
        is_wikipedia = graph_info and graph_info.get("graph_type") == "wikipedia"
        
        if is_wikipedia:
            # Wikipedia-specific optimizations
            if "traversal" in result:
                # Prioritize high-quality relationship types in Wikipedia
                if "edge_types" in result["traversal"]:
                    edge_types = result["traversal"]["edge_types"]
                    # Prioritize more reliable Wikipedia relationships
                    priority_edges = ["instance_of", "subclass_of", "part_of", "located_in"]
                    
                    # Move priority edge types to the beginning
                    for edge_type in reversed(priority_edges):
                        if edge_type in edge_types:
                            edge_types.remove(edge_type)
                            edge_types.insert(0, edge_type)
                            
                    result["traversal"]["edge_types"] = edge_types
                    
                # For Wikipedia, trust hierarchical relationships more
                result["traversal"]["hierarchical_weight"] = 1.5
                
        return result
    
    def _detect_query_pattern(self, query: Dict[str, Any]) -> str:
        """
        Detects the query pattern type from the query structure.
        
        Args:
            query (Dict): Query to analyze
            
        Returns:
            str: Detected pattern type
        """
        if "entity_id" in query or "entity_name" in query:
            return "entity_lookup"
        elif "fact" in query or ("source_entity" in query and "target_entity" in query):
            return "fact_verification"
        elif "relation_type" in query or (
            "traversal" in query and "edge_types" in query["traversal"] and len(query["traversal"]["edge_types"]) == 1
        ):
            return "relation_centric"
        elif "query_text" in query and len(query.get("query_text", "")) > 50:
            return "complex_question"
        else:
            return "general"
            
    def analyze_query(self, query: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes a query to determine its characteristics and potential optimizations.
        
        Args:
            query (Dict): Query to analyze
            
        Returns:
            Dict: Analysis results
        """
        analysis = {
            "pattern": self._detect_query_pattern(query),
            "complexity": self._estimate_query_complexity(query),
            "optimizations": []
        }
        
        # Check for potential optimizations
        if "min_similarity" in query and query["min_similarity"] < 0.5:
            analysis["optimizations"].append({
                "type": "threshold_increase",
                "description": "Consider increasing min_similarity to improve precision"
            })
            
        if "traversal" in query and query["traversal"].get("max_depth", 0) > 3:
            analysis["optimizations"].append({
                "type": "depth_reduction",
                "description": "Deep traversal may cause performance issues, consider reducing max_depth"
            })
            
        return analysis
        
    def _estimate_query_complexity(self, query: Dict[str, Any]) -> str:
        """
        Estimates the complexity of a query.
        
        Args:
            query (Dict): Query to analyze
            
        Returns:
            str: Complexity level ("low", "medium", "high")
        """
        complexity_score = 0
        
        # Vector search complexity
        vector_params = query.get("vector_params", {})
        complexity_score += vector_params.get("top_k", 5) * 0.5
        
        # Traversal complexity
        traversal = query.get("traversal", {})
        max_depth = traversal.get("max_depth", 0)
        complexity_score += max_depth * 2  # Depth has exponential impact
        
        # Edge type complexity
        edge_types = traversal.get("edge_types", [])
        complexity_score += len(edge_types) * 0.3
        
        # Determine complexity level
        if complexity_score < 5:
            return "low"
        elif complexity_score < 12:
            return "medium"
        else:
            return "high"


class QueryBudgetManager:
    """
    Manages query execution resources through adaptive budgeting.
    
    Features:
    - Dynamic resource allocation based on query priority and complexity
    - Early stopping based on result quality and diminishing returns
    - Adaptive computation budgeting based on query history
    - Progressive query expansion driven by initial results
    - Timeout management and cost estimation
    """
    
    def __init__(self, default_budget: Dict[str, float] = None):
        """
        Initialize the budget manager.
        
        Args:
            default_budget (Dict[str, float], optional): Default budget values for
                different resource types
        """
        self.default_budget = default_budget or {
            "vector_search_ms": 500.0,    # Vector search budget in milliseconds
            "graph_traversal_ms": 1000.0, # Graph traversal budget in milliseconds
            "ranking_ms": 200.0,          # Ranking budget in milliseconds
            "max_nodes": 1000,            # Maximum nodes to visit
            "max_edges": 5000,            # Maximum edges to traverse
            "timeout_ms": 2000.0          # Total query timeout in milliseconds
        }
        
        # Track budget consumption history
        self.budget_history = {
            "vector_search_ms": [],
            "graph_traversal_ms": [],
            "ranking_ms": [],
            "nodes_visited": [],
            "edges_traversed": []
        }
        
        self.current_consumption = {}
        
    def allocate_budget(self, query: Dict[str, Any], priority: str = "normal") -> Dict[str, float]:
        """
        Allocate budget for a query based on its characteristics and priority.
        
        Args:
            query (Dict): Query to execute
            priority (str): Priority level ("low", "normal", "high", "critical")
            
        Returns:
            Dict: Allocated budget
        """
        # Start with default budget
        budget = self.default_budget.copy()
        
        # Adjust based on query complexity
        query_complexity = self._estimate_complexity(query)
        complexity_multiplier = {
            "low": 0.7,
            "medium": 1.0,
            "high": 1.5,
            "very_high": 2.0
        }
        
        # Apply complexity multiplier
        for resource in budget:
            budget[resource] *= complexity_multiplier.get(query_complexity, 1.0)
            
        # Apply priority multiplier
        priority_multiplier = {
            "low": 0.5,
            "normal": 1.0,
            "high": 2.0,
            "critical": 5.0
        }
        
        for resource in budget:
            budget[resource] *= priority_multiplier.get(priority, 1.0)
            
        # Adjust based on historical consumption
        self._apply_historical_adjustment(budget)
        
        # Initialize consumption tracking
        self.current_consumption = {
            "vector_search_ms": 0.0,
            "graph_traversal_ms": 0.0,
            "ranking_ms": 0.0,
            "nodes_visited": 0,
            "edges_traversed": 0
        }
        
        return budget
        
    def track_consumption(self, resource: str, amount: float) -> None:
        """
        Track resource consumption during query execution.
        
        Args:
            resource (str): Resource type
            amount (float): Amount consumed
        """
        if resource in self.current_consumption:
            self.current_consumption[resource] += amount
            
    def is_budget_exceeded(self, resource: str) -> bool:
        """
        Check if a resource's budget has been exceeded.
        
        Args:
            resource (str): Resource type
            
        Returns:
            bool: Whether the budget has been exceeded
        """
        if resource not in self.current_consumption or resource not in self.default_budget:
            return False
        
        # Check if consumption exceeds budget
        return self.current_consumption[resource] > self.default_budget[resource]
    
    def record_completion(self, success: bool = True) -> None:
        """
        Record query completion and update budget history.
        
        Args:
            success (bool): Whether the query completed successfully
        """
        # Update budget history
        for resource, consumed in self.current_consumption.items():
            if resource in self.budget_history:
                self.budget_history[resource].append(consumed)
                
                # Keep history manageable
                if len(self.budget_history[resource]) > 100:
                    self.budget_history[resource] = self.budget_history[resource][-100:]
    
    def _estimate_complexity(self, query: Dict[str, Any]) -> str:
        """
        Estimate query complexity for budget allocation.
        
        Args:
            query (Dict): Query to analyze
            
        Returns:
            str: Complexity level
        """
        # Vector search complexity
        vector_params = query.get("vector_params", {})
        complexity_score = 0
        complexity_score += vector_params.get("top_k", 5) * 0.5
        
        # Traversal complexity
        traversal = query.get("traversal", {})
        max_depth = traversal.get("max_depth", 0)
        complexity_score += max_depth * 2  # Depth has exponential impact
        
        # Edge type complexity
        edge_types = traversal.get("edge_types", [])
        complexity_score += len(edge_types) * 0.3
        
        # Determine complexity level
        if complexity_score < 5:
            return "low"
        elif complexity_score < 10:
            return "medium"
        elif complexity_score < 20:
            return "high"
        else:
            return "very_high"
    
    def _apply_historical_adjustment(self, budget: Dict[str, float]) -> None:
        """
        Adjust budget based on historical consumption patterns.
        
        Args:
            budget (Dict): Budget to adjust
        """
        # For each resource, analyze historical usage
        for resource, history in self.budget_history.items():
            if not history:
                continue
                
            # Calculate average consumption
            avg_consumption = sum(history) / len(history)
            
            # Calculate 95th percentile (approximation)
            sorted_history = sorted(history)
            p95_idx = min(int(len(sorted_history) * 0.95), len(sorted_history) - 1)
            p95_consumption = sorted_history[p95_idx]
            
            # Adjust budget to be between average and 95th percentile
            if resource in budget:
                adjusted = (avg_consumption + p95_consumption) / 2
                # Ensure budget is not reduced below 80% of default
                min_budget = self.default_budget.get(resource, 0) * 0.8
                budget[resource] = max(adjusted, min_budget)
    
    def suggest_early_stopping(self, current_results: List[Dict[str, Any]], budget_consumed_ratio: float) -> bool:
        """
        Suggest whether to stop query execution early based on result quality
        and resource consumption.
        
        Args:
            current_results (List[Dict]): Current query results
            budget_consumed_ratio (float): Ratio of consumed budget
            
        Returns:
            bool: Whether to stop early
        """
        # If minimal results, don't stop
        if len(current_results) < 3:
            return False
            
        # If budget heavily consumed, check result quality
        if budget_consumed_ratio > 0.7:
            # Calculate average score of top 3 results
            if all("score" in r for r in current_results[:3]):
                avg_top_score = sum(r["score"] for r in current_results[:3]) / 3
                
                # If high quality results already found
                if avg_top_score > 0.85:
                    return True
                    
        # Check for score diminishing returns
        if len(current_results) > 5:
            # Check if scores are plateauing
            if all("score" in r for r in current_results):
                scores = [r["score"] for r in current_results]
                top_score = scores[0]
                fifth_score = scores[4]
                
                # If drop-off is significant
                if top_score - fifth_score > 0.3:
                    return True
        
        return False
        
    def get_current_consumption_report(self) -> Dict[str, Any]:
        """
        Get a report of current resource consumption.
        
        Returns:
            Dict: Resource consumption report
        """
        report = self.current_consumption.copy()
        
        # Add budget info
        report["budget"] = self.default_budget.copy()
        
        # Calculate consumption ratios
        report["ratios"] = {}
        for resource, consumed in self.current_consumption.items():
            if resource in self.default_budget and self.default_budget[resource] > 0:
                report["ratios"][resource] = consumed / self.default_budget[resource]
            else:
                report["ratios"][resource] = 0.0
                
        # Overall consumption
        if report["ratios"]:
            report["overall_consumption_ratio"] = sum(report["ratios"].values()) / len(report["ratios"])
        else:
            report["overall_consumption_ratio"] = 0.0
            
        return report


class UnifiedGraphRAGQueryOptimizer:
    """
    Combines optimization strategies for different graph types.
    
    Features:
    - Auto-detection of graph type from query parameters
    - Wikipedia-specific and IPLD-specific optimizations
    - Cross-graph query planning for heterogeneous environments
    - Comprehensive performance analysis and recommendation generation
    - Integration with advanced rewriting and budget management
    """
    
    def __init__(self, 
                 rewriter: Optional[QueryRewriter] = None,
                 budget_manager: Optional[QueryBudgetManager] = None,
                 base_optimizer: Optional[GraphRAGQueryOptimizer] = None,
                 graph_info: Optional[Dict[str, Any]] = None):
        """
        Initialize the unified optimizer.
        
        Args:
            rewriter (QueryRewriter, optional): Query rewriter
            budget_manager (QueryBudgetManager, optional): Query budget manager
            base_optimizer (GraphRAGQueryOptimizer, optional): Base query optimizer
            graph_info (Dict, optional): Graph information for optimizations
        """
        self.rewriter = rewriter or QueryRewriter()
        self.budget_manager = budget_manager or QueryBudgetManager()
        self.base_optimizer = base_optimizer or GraphRAGQueryOptimizer()
        self.graph_info = graph_info or {}
        self.query_stats = self.base_optimizer.query_stats
        
        # Specialized optimizers by graph type
        self._specific_optimizers = {}
        self._setup_specific_optimizers()
    
    def _setup_specific_optimizers(self) -> None:
        """Set up specialized optimizers for different graph types."""
        # Wikipedia-specific optimizer
        # (Inherits from base optimizer but has specific optimizations)
        wiki_optimizer = GraphRAGQueryOptimizer(
            query_stats=self.query_stats,
            vector_weight=0.6,  # Wikipedia weight adjustment
            graph_weight=0.4,   # Focus more on graph structure in Wikipedia
            cache_ttl=600.0     # Longer cache for Wikipedia queries
        )
        
        # IPLD-specific optimizer
        ipld_optimizer = GraphRAGQueryOptimizer(
            query_stats=self.query_stats,
            vector_weight=0.75,  # IPLD weight adjustment
            graph_weight=0.25,   # IPLD-specific weight
            cache_ttl=300.0      # Standard cache for IPLD
        )
        
        # Register specialized optimizers
        self._specific_optimizers = {
            "wikipedia": wiki_optimizer,
            "ipld": ipld_optimizer,
            "general": self.base_optimizer
        }
    
    def detect_graph_type(self, query: Dict[str, Any]) -> str:
        """
        Detect the graph type from the query parameters.
        
        Args:
            query (Dict): Query parameters
            
        Returns:
            str: Detected graph type
        """
        # Look for explicit graph type
        if "graph_type" in query:
            return query["graph_type"]
            
        # Check for Wikipedia-specific signals
        if any(kw in str(query).lower() for kw in ["wikipedia", "wikidata", "dbpedia"]):
            return "wikipedia"
            
        # Check for IPLD-specific signals
        if any(kw in str(query).lower() for kw in ["ipld", "content-addressed", "cid", "dag", "ipfs"]):
            return "ipld"
        
        # Default to general
        return "general"
    
    def optimize_query(self, query: Dict[str, Any], priority: str = "normal") -> Dict[str, Any]:
        """
        Generate an optimized query plan with unified optimizations.
        
        Args:
            query (Dict): Query to optimize
            priority (str): Query priority
            
        Returns:
            Dict: Optimized query plan
        """
        # Detect graph type
        graph_type = self.detect_graph_type(query)
        
        # Get the appropriate optimizer
        optimizer = self._specific_optimizers.get(graph_type, self.base_optimizer)
        
        # First, apply query rewriting
        rewritten_query = self.rewriter.rewrite_query(query, self.graph_info)
        
        # Then, get specialized optimization parameters
        if "query_vector" in rewritten_query:
            # For vector-based queries
            optimized_params = optimizer.optimize_query(
                query_vector=rewritten_query["query_vector"],
                max_vector_results=rewritten_query.get("max_vector_results", 5),
                max_traversal_depth=rewritten_query.get("max_traversal_depth", 2),
                edge_types=rewritten_query.get("edge_types"),
                min_similarity=rewritten_query.get("min_similarity", 0.5)
            )
        else:
            # For non-vector queries, just pass through
            optimized_params = {"params": rewritten_query, "weights": {}}
        
        # Allocate budget
        budget = self.budget_manager.allocate_budget(rewritten_query, priority)
        
        # Create the final query plan
        plan = {
            "query": optimized_params["params"],
            "weights": optimized_params["weights"],
            "budget": budget,
            "graph_type": graph_type,
            "statistics": {
                "avg_query_time": self.query_stats.avg_query_time,
                "cache_hit_rate": self.query_stats.cache_hit_rate
            },
            "caching": {
                "enabled": optimizer.cache_enabled
            }
        }
        
        # Add query key if caching is enabled
        if optimizer.cache_enabled and "query_vector" in rewritten_query:
            plan["caching"]["key"] = optimizer.get_query_key(
                rewritten_query["query_vector"],
                optimized_params["params"].get("max_vector_results", 5),
                optimized_params["params"].get("max_traversal_depth", 2),
                optimized_params["params"].get("edge_types"),
                optimized_params["params"].get("min_similarity", 0.5)
            )
            
        return plan
    
    def execute_query(
        self,
        processor: Any,
        query: Dict[str, Any],
        priority: str = "normal",
        skip_cache: bool = False
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Execute a GraphRAG query with unified optimizations.
        
        Args:
            processor: GraphRAG processor implementation
            query (Dict): Query to execute
            priority (str): Query priority
            skip_cache (bool): Whether to skip cache
            
        Returns:
            Tuple[List[Dict], Dict]: (Results, execution_info)
        """
        # Generate optimized query plan
        plan = self.optimize_query(query, priority)
        graph_type = plan["graph_type"]
        
        # Get specialized optimizer
        optimizer = self._specific_optimizers.get(graph_type, self.base_optimizer)
        
        # Check cache if enabled and not skipped
        if optimizer.cache_enabled and not skip_cache and "key" in plan["caching"]:
            cache_key = plan["caching"]["key"]
            if optimizer.is_in_cache(cache_key):
                results = optimizer.get_from_cache(cache_key)
                return results, {"from_cache": True, "plan": plan}
        
        # Start timing query execution
        start_time = time.time()
        
        # Execute query based on type
        if "query_vector" in query:
            # Vector-based query
            query_vector = query["query_vector"]
            params = plan["query"]
            
            # Execute the query phases with budget tracking
            # 1. Vector search phase
            vector_search_start = time.time()
            vector_results = processor.search_by_vector(
                query_vector,
                top_k=params.get("max_vector_results", 5),
                min_score=params.get("min_similarity", 0.5)
            )
            vector_search_time = (time.time() - vector_search_start) * 1000  # in ms
            self.budget_manager.track_consumption("vector_search_ms", vector_search_time)
            
            # Check for early stopping after vector search
            if not vector_results:
                execution_time = time.time() - start_time
                self.query_stats.record_query_time(execution_time)
                return [], {"from_cache": False, "execution_time": execution_time, "plan": plan}
            
            # 2. Graph traversal phase
            graph_traversal_start = time.time()
            graph_results = processor.expand_by_graph(
                vector_results,
                max_depth=params.get("max_traversal_depth", 2),
                edge_types=params.get("edge_types")
            )
            graph_traversal_time = (time.time() - graph_traversal_start) * 1000  # in ms
            self.budget_manager.track_consumption("graph_traversal_ms", graph_traversal_time)
            
            # Check for early stopping after graph traversal
            consumption_report = self.budget_manager.get_current_consumption_report()
            if self.budget_manager.suggest_early_stopping(graph_results, consumption_report["overall_consumption_ratio"]):
                execution_time = time.time() - start_time
                self.query_stats.record_query_time(execution_time)
                # Cache results even on early stopping
                if optimizer.cache_enabled:
                    optimizer.add_to_cache(plan["caching"]["key"], graph_results)
                return graph_results, {
                    "from_cache": False, 
                    "execution_time": execution_time, 
                    "early_stopping": True,
                    "plan": plan,
                    "consumption": consumption_report
                }
            
            # 3. Result ranking phase
            ranking_start = time.time()
            combined_results = processor.rank_results(
                graph_results,
                vector_weight=plan["weights"].get("vector", 0.7),
                graph_weight=plan["weights"].get("graph", 0.3)
            )
            ranking_time = (time.time() - ranking_start) * 1000  # in ms
            self.budget_manager.track_consumption("ranking_ms", ranking_time)
        else:
            # Non-vector query (direct graph query)
            combined_results = processor.direct_graph_query(query)
            
        # Record completion and execution time
        execution_time = time.time() - start_time
        self.query_stats.record_query_time(execution_time)
        self.budget_manager.record_completion(success=True)
        
        # Cache result if enabled
        if optimizer.cache_enabled and "key" in plan["caching"]:
            optimizer.add_to_cache(plan["caching"]["key"], combined_results)
        
        # Return results and execution info
        consumption_report = self.budget_manager.get_current_consumption_report()
        execution_info = {
            "from_cache": False,
            "execution_time": execution_time,
            "plan": plan,
            "consumption": consumption_report
        }
        
        return combined_results, execution_info
    
    def analyze_performance(self, recent_window_seconds: float = 300.0) -> Dict[str, Any]:
        """
        Analyze and generate recommendations for query performance.
        
        Args:
            recent_window_seconds (float): Time window for recent queries
            
        Returns:
            Dict: Performance analysis and recommendations
        """
        # Get basic query statistics
        recent_times = self.query_stats.get_recent_query_times(recent_window_seconds)
        common_patterns = self.query_stats.get_common_patterns()
        
        analysis = {
            "query_count": self.query_stats.query_count,
            "cache_hit_rate": self.query_stats.cache_hit_rate,
            "avg_query_time": self.query_stats.avg_query_time,
            "recent_avg_time": sum(recent_times) / len(recent_times) if recent_times else 0.0,
            "common_patterns": common_patterns,
            "recommendations": []
        }
        
        # Generate recommendations based on statistics
        if analysis["cache_hit_rate"] < 0.3 and analysis["query_count"] > 20:
            analysis["recommendations"].append({
                "type": "cache_tuning",
                "description": "Low cache hit rate. Consider increasing cache size or TTL."
            })
            
        if analysis["avg_query_time"] > 1.0:
            analysis["recommendations"].append({
                "type": "query_optimization",
                "description": "High average query time. Consider reducing traversal depth or vector results."
            })
            
        # Check for patterns with high complexity
        for pattern, count in common_patterns:
            if "max_traversal_depth" in pattern and pattern["max_traversal_depth"] > 3:
                analysis["recommendations"].append({
                    "type": "traversal_depth",
                    "description": f"Common query pattern with high traversal depth ({pattern['max_traversal_depth']}). Consider reducing depth."
                })
                
        # Check for resource consumption patterns
        consumption_report = self.budget_manager.get_current_consumption_report()
        for resource, ratio in consumption_report["ratios"].items():
            if ratio > 0.9:
                analysis["recommendations"].append({
                    "type": "resource_limit",
                    "description": f"Resource {resource} consistently near budget limit. Consider increasing budget."
                })
                
        return analysis
        
    def get_execution_plan(self, query: Dict[str, Any], priority: str = "normal") -> Dict[str, Any]:
        """
        Generate a detailed execution plan without executing the query.
        
        Args:
            query (Dict): Query to plan
            priority (str): Query priority
            
        Returns:
            Dict: Detailed execution plan
        """
        # Optimize query
        plan = self.optimize_query(query, priority)
        
        # Determine graph type
        graph_type = plan["graph_type"]
        
        # Create execution steps
        execution_steps = []
        
        if "query_vector" in query:
            # Vector-based query
            execution_steps = [
                {
                    "name": "vector_similarity_search",
                    "description": "Find initial matches by vector similarity",
                    "budget_ms": plan["budget"]["vector_search_ms"],
                    "params": {
                        "query_vector": "[vector data]",  # Placeholder
                        "top_k": plan["query"].get("max_vector_results", 5),
                        "min_score": plan["query"].get("min_similarity", 0.5)
                    }
                },
                {
                    "name": "graph_traversal",
                    "description": "Expand matches through graph traversal",
                    "budget_ms": plan["budget"]["graph_traversal_ms"],
                    "params": {
                        "max_depth": plan["query"].get("max_traversal_depth", 2),
                        "edge_types": plan["query"].get("edge_types", []),
                        "max_nodes": plan["budget"]["max_nodes"]
                    }
                },
                {
                    "name": "result_ranking",
                    "description": "Rank combined results",
                    "budget_ms": plan["budget"]["ranking_ms"],
                    "params": {
                        "vector_weight": plan["weights"].get("vector", 0.7),
                        "graph_weight": plan["weights"].get("graph", 0.3)
                    }
                }
            ]
        else:
            # Direct graph query
            execution_steps = [
                {
                    "name": "direct_graph_query",
                    "description": "Execute direct graph query",
                    "budget_ms": plan["budget"]["graph_traversal_ms"],
                    "params": plan["query"]
                }
            ]
            
        # Add caching information
        caching_info = plan["caching"].copy()
        if "key" in caching_info:
            caching_info["key"] = caching_info["key"][:10] + "..."  # Truncate for readability
            
        # Return detailed plan
        return {
            "graph_type": graph_type,
            "optimization_applied": True,
            "execution_steps": execution_steps,
            "caching": caching_info,
            "budget": plan["budget"],
            "statistics": plan["statistics"],
            "estimated_time_ms": sum(step["budget_ms"] for step in execution_steps),
            "priority": priority
        }
    
    def execute_query_with_caching(
        self,
        query_func: Callable[[np.ndarray, Dict[str, Any]], Any],
        query_vector: np.ndarray,
        params: Dict[str, Any]
    ) -> Any:
        """
        Execute a query with caching and performance tracking.
        
        Args:
            query_func (Callable): Function that executes the query
            query_vector (np.ndarray): Query vector
            params (Dict): Query parameters
            
        Returns:
            Any: Query results
        """
        # Create query representation
        query = {
            "query_vector": query_vector,
            **params
        }
        
        # Generate optimized plan
        plan = self.optimize_query(query)
        
        # Check cache
        if "key" in plan["caching"] and plan["caching"]["enabled"]:
            cache_key = plan["caching"]["key"]
            optimizer = self._specific_optimizers.get(plan["graph_type"], self.base_optimizer)
            if optimizer.is_in_cache(cache_key):
                return optimizer.get_from_cache(cache_key)
        
        # Execute query
        start_time = time.time()
        results = query_func(query_vector, params)
        execution_time = time.time() - start_time
        
        # Track statistics
        self.query_stats.record_query_time(execution_time)
        
        # Cache results
        if "key" in plan["caching"] and plan["caching"]["enabled"]:
            optimizer = self._specific_optimizers.get(plan["graph_type"], self.base_optimizer)
            optimizer.add_to_cache(plan["caching"]["key"], results)
            
        return results


def example_usage():
    """Example usage of the RAG Query Optimizer components."""
    # Sample query vector (would come from an embedding model in real usage)
    query_vector = np.random.rand(768)
    
    # Initialize components
    stats = GraphRAGQueryStats()
    optimizer = GraphRAGQueryOptimizer(query_stats=stats)
    query_rewriter = QueryRewriter()
    budget_manager = QueryBudgetManager()
    
    # Create the unified optimizer
    unified_optimizer = UnifiedGraphRAGQueryOptimizer(
        rewriter=query_rewriter,
        budget_manager=budget_manager,
        base_optimizer=optimizer,
        graph_info={
            "graph_type": "wikipedia",
            "edge_selectivity": {
                "instance_of": 0.1,
                "subclass_of": 0.05,
                "part_of": 0.2,
                "located_in": 0.15,
                "created_by": 0.3
            },
            "graph_density": 0.4
        }
    )
    
    # Create a sample query
    query = {
        "query_vector": query_vector,
        "max_vector_results": 10,
        "max_traversal_depth": 3,
        "edge_types": ["instance_of", "part_of", "created_by"],
        "min_similarity": 0.6,
        "query_text": "What is the relationship between quantum mechanics and general relativity?"
    }
    
    # Get a detailed execution plan
    plan = unified_optimizer.get_execution_plan(query, priority="high")
    print(f"Execution Plan: {json.dumps(plan, indent=2)}")
    
    # In a real system, you would implement these methods in your GraphRAG processor
    class MockGraphRAGProcessor:
        def search_by_vector(self, vector, top_k=5, min_score=0.5):
            # Simulate vector search
            return [
                {"id": f"entity_{i}", "score": 0.9 - (i * 0.05), "text": f"Sample entity {i}"} 
                for i in range(top_k)
            ]
            
        def expand_by_graph(self, entities, max_depth=2, edge_types=None):
            # Simulate graph traversal
            results = entities.copy()
            # Add some related entities
            for i in range(len(entities)):
                related = [
                    {"id": f"related_{i}_{j}", "score": 0.8 - (j * 0.1), "text": f"Related to {i}, item {j}"}
                    for j in range(3)
                ]
                results.extend(related)
            return results
            
        def rank_results(self, results, vector_weight=0.7, graph_weight=0.3):
            # Simulate result ranking
            # Sort by score
            return sorted(results, key=lambda x: x["score"], reverse=True)
            
        def direct_graph_query(self, query):
            # Simulate direct graph query
            return [
                {"id": f"direct_{i}", "score": 0.85 - (i * 0.05), "text": f"Direct graph result {i}"}
                for i in range(5)
            ]
    
    # Create a processor instance
    processor = MockGraphRAGProcessor()
    
    # Execute the query
    results, execution_info = unified_optimizer.execute_query(processor, query, priority="high")
    
    # Print execution info
    print(f"Execution Info: {json.dumps(execution_info, indent=2, default=str)}")
    
    # Print results (truncated for brevity)
    print(f"Results: {results[:3]}")
    
    # Analyze performance
    performance_analysis = unified_optimizer.analyze_performance()
    print(f"Performance Analysis: {json.dumps(performance_analysis, indent=2)}")
    
    # Demonstrate query rewriting
    original_query = {
        "entity_types": ["Person", "Organization"],
        "min_similarity": 0.4,
        "traversal": {
            "max_depth": 4,
            "edge_types": ["knows", "works_for", "founded"]
        }
    }
    
    rewritten = query_rewriter.rewrite_query(original_query, unified_optimizer.graph_info)
    print(f"Original Query: {json.dumps(original_query, indent=2)}")
    print(f"Rewritten Query: {json.dumps(rewritten, indent=2)}")
    
    # Demonstrate budget management
    budget = budget_manager.allocate_budget(query, priority="critical")
    print(f"Allocated Budget: {json.dumps(budget, indent=2)}")
    
    # Track some resource consumption
    budget_manager.track_consumption("vector_search_ms", 250.0)
    budget_manager.track_consumption("graph_traversal_ms", 800.0)
    budget_manager.track_consumption("nodes_visited", 500)
    
    # Get consumption report
    consumption_report = budget_manager.get_current_consumption_report()
    print(f"Consumption Report: {json.dumps(consumption_report, indent=2)}")
    
    return "Example completed successfully"


if __name__ == "__main__":
    # Run the example usage function to demonstrate the RAG Query Optimizer
    example_usage()