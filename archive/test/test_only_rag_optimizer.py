"""
Test RAG Query Optimizer functionality in isolation.
"""

import unittest
import numpy as np
import time
from typing import Dict, List, Any, Optional, Tuple

# Implementations for testing

class GraphRAGQueryStats:
    """
    Collects and analyzes query statistics for optimization purposes.
    """

    def __init__(self):
        """Initialize the query statistics tracker."""
        self.query_count = 0
        self.cache_hits = 0
        self.total_query_time = 0.0
        self.query_times = []
        self.query_patterns = {}
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
        """Record the execution time of a query."""
        self.query_count += 1
        self.total_query_time += execution_time
        self.query_times.append(execution_time)
        self.query_timestamps.append(time.time())

    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.cache_hits += 1

    def record_query_pattern(self, pattern: Dict[str, Any]) -> None:
        """Record a query pattern for analysis."""
        # Convert the pattern to a hashable representation
        pattern_key = str(sorted(pattern.items()))
        if pattern_key in self.query_patterns:
            self.query_patterns[pattern_key] += 1
        else:
            self.query_patterns[pattern_key] = 1

    def get_common_patterns(self, top_n: int = 5) -> List[Tuple[Dict[str, Any], int]]:
        """Get the most common query patterns."""
        # Sort patterns by frequency
        sorted_patterns = sorted(self.query_patterns.items(), key=lambda x: x[1], reverse=True)

        # Only keep top_n patterns
        top_patterns = sorted_patterns[:top_n]

        # Convert back to dictionaries
        result = []
        for pattern_str, count in top_patterns:
            # Approximate conversion back to dict - this is a simplified version
            pattern_dict = {}
            for item in pattern_str.strip("[]").split(", "):
                if ":" in item:
                    key, value = item.split(":", 1)
                    pattern_dict[key.strip("'")] = value.strip()
            result.append((pattern_dict, count))

        return result

    def get_recent_query_times(self, window_seconds: float = 300.0) -> List[float]:
        """Get query times from the recent time window."""
        current_time = time.time()
        cutoff_time = current_time - window_seconds

        # Filter query times by timestamp
        recent_times = []
        for i, timestamp in enumerate(self.query_timestamps):
            if timestamp >= cutoff_time:
                recent_times.append(self.query_times[i])

        return recent_times


class QueryRewriter:
    """
    Analyzes and rewrites queries for better performance.
    """

    def __init__(self, traversal_stats=None):
        """Initialize the query rewriter."""
        self.traversal_stats = traversal_stats or {
            "paths_explored": [],
            "path_scores": {},
            "entity_frequency": {},
            "entity_connectivity": {},
            "relation_usefulness": {}
        }

    def rewrite_query(self, query, graph_info=None, entity_scores=None):
        """
        Rewrite a query for better performance.

        Args:
            query: Original query
            graph_info: Information about the graph structure
            entity_scores: Entity importance scores

        Returns:
            Dict: Rewritten query
        """
        # Start with a copy of the original query
        rewritten = query.copy()

        # Apply predicate pushdown
        if "min_similarity" in rewritten and "vector_params" not in rewritten:
            rewritten["vector_params"] = {"min_score": rewritten.pop("min_similarity")}
        elif "min_similarity" in rewritten and "vector_params" in rewritten:
            rewritten["vector_params"]["min_score"] = rewritten.pop("min_similarity")

        if "entity_filters" in rewritten and "entity_types" in rewritten.get("entity_filters", {}):
            if "vector_params" not in rewritten:
                rewritten["vector_params"] = {}
            rewritten["vector_params"]["entity_types"] = rewritten["entity_filters"]["entity_types"]
            del rewritten["entity_filters"]

        # Reorder joins by selectivity if graph_info provided
        if "traversal" in rewritten and "edge_types" in rewritten["traversal"] and graph_info and "edge_selectivity" in graph_info:
            edge_types = rewritten["traversal"]["edge_types"]
            selectivity = graph_info["edge_selectivity"]

            # Sort by selectivity (lowest first - most selective)
            edge_types.sort(key=lambda et: selectivity.get(et, 0.5))
            rewritten["traversal"]["edge_types"] = edge_types
            rewritten["traversal"]["reordered_by_selectivity"] = True

        # Optimize traversal path
        if "traversal" in rewritten:
            max_depth = rewritten["traversal"].get("max_depth", 0)

            # For deep traversal, use breadth-limited strategy
            if max_depth > 2:
                rewritten["traversal"]["strategy"] = "breadth_limited"
                rewritten["traversal"]["max_breadth_per_level"] = 5

            # For dense graphs, use sampling
            if graph_info and graph_info.get("graph_density", 0) > 0.7:
                rewritten["traversal"]["strategy"] = "sampling"
                rewritten["traversal"]["sample_ratio"] = 0.3

        # Apply pattern-specific optimizations
        pattern = self._detect_query_pattern(rewritten)
        if pattern == "entity_lookup" and "entity_id" in rewritten:
            rewritten["skip_vector_search"] = True
        elif pattern == "relation_centric":
            if "traversal" not in rewritten:
                rewritten["traversal"] = {}
            rewritten["traversal"]["prioritize_relationships"] = True
        elif pattern == "fact_verification":
            if "traversal" not in rewritten:
                rewritten["traversal"] = {}
            rewritten["traversal"]["strategy"] = "path_finding"
            rewritten["traversal"]["find_shortest_path"] = True

        # Apply Wikipedia-specific optimizations if needed
        is_wikipedia = graph_info and graph_info.get("graph_type") == "wikipedia"
        if is_wikipedia and "traversal" in rewritten and "edge_types" in rewritten["traversal"]:
            edge_types = rewritten["traversal"]["edge_types"]
            priority_edges = ["instance_of", "subclass_of", "part_of", "located_in"]

            # Move priority edges to the front
            for edge_type in reversed(priority_edges):
                if edge_type in edge_types:
                    edge_types.remove(edge_type)
                    edge_types.insert(0, edge_type)

            rewritten["traversal"]["edge_types"] = edge_types
            rewritten["traversal"]["hierarchical_weight"] = 1.5

        return rewritten

    def _detect_query_pattern(self, query):
        """Detect the query pattern type from the query structure."""
        if "entity_id" in query or "entity_name" in query:
            return "entity_lookup"
        elif "source_entity" in query and "target_entity" in query:
            return "fact_verification"
        elif "relation_type" in query or (
            "traversal" in query and "edge_types" in query["traversal"] and len(query["traversal"]["edge_types"]) == 1
        ):
            return "relation_centric"
        else:
            return "general"

    def _estimate_query_complexity(self, query):
        """Estimate the complexity of a query."""
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
    """

    def __init__(self, default_budget=None):
        """Initialize the budget manager."""
        self.default_budget = default_budget or {
            "vector_search_ms": 500.0,
            "graph_traversal_ms": 1000.0,
            "ranking_ms": 200.0,
            "max_nodes": 1000,
            "max_edges": 5000,
            "timeout_ms": 2000.0
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

    def allocate_budget(self, query, priority="normal"):
        """
        Allocate budget for a query based on its characteristics and priority.

        Args:
            query: Query to execute
            priority: Priority level ("low", "normal", "high", "critical")

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

        # Initialize consumption tracking
        self.current_consumption = {
            "vector_search_ms": 0.0,
            "graph_traversal_ms": 0.0,
            "ranking_ms": 0.0,
            "nodes_visited": 0,
            "edges_traversed": 0
        }

        return budget

    def track_consumption(self, resource, amount):
        """Track resource consumption during query execution."""
        if resource in self.current_consumption:
            self.current_consumption[resource] += amount

    def reset_consumption(self):
        """Reset current consumption tracking."""
        self.current_consumption = {
            "vector_search_ms": 0.0,
            "graph_traversal_ms": 0.0,
            "ranking_ms": 0.0,
            "nodes_visited": 0,
            "edges_traversed": 0
        }

    def get_consumption(self, resource):
        """Get current consumption for a resource."""
        return self.current_consumption.get(resource, 0.0)

    def record_completion(self, success=True):
        """Record query completion and update budget history."""
        # Update budget history
        for resource, consumed in self.current_consumption.items():
            if resource in self.budget_history:
                self.budget_history[resource].append(consumed)

                # Keep history manageable
                if len(self.budget_history[resource]) > 100:
                    self.budget_history[resource] = self.budget_history[resource][-100:]

    def _estimate_complexity(self, query):
        """Estimate query complexity for budget allocation."""
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

    def suggest_early_stopping(self, current_results, budget_consumed_ratio):
        """
        Suggest whether to stop query execution early based on result quality
        and resource consumption.
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

    def get_current_consumption_report(self):
        """Get a report of current resource consumption."""
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


class GraphRAGQueryOptimizer:
    """
    Optimizes query execution for GraphRAG operations.
    """

    def __init__(
        self,
        query_stats=None,
        vector_weight=0.7,
        graph_weight=0.3,
        cache_enabled=True,
        cache_ttl=300.0,
        cache_size_limit=100
    ):
        """Initialize the query optimizer."""
        self.query_stats = query_stats or GraphRAGQueryStats()
        self.vector_weight = vector_weight
        self.graph_weight = graph_weight
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self.cache_size_limit = cache_size_limit

        # Query cache
        self.query_cache = {}

    def optimize_query(
        self,
        query_vector,
        max_vector_results=5,
        max_traversal_depth=2,
        edge_types=None,
        min_similarity=0.5
    ):
        """
        Generate an optimized query plan based on statistics and preferences.
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
                common_depth = max(set(depths), key=depths.count) if depths else 2
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

    def get_query_key(self, query_vector, max_vector_results=5, max_traversal_depth=2, edge_types=None, min_similarity=0.5):
        """Generate a unique key for a query for caching purposes."""
        # Create a dictionary of query parameters
        query_params = {
            "vector": str(query_vector)[:100],  # Truncate for reasonable key size
            "max_vector_results": max_vector_results,
            "max_traversal_depth": max_traversal_depth,
            "edge_types": str(edge_types),
            "min_similarity": min_similarity
        }

        # Convert to string for cache key
        return str(sorted(query_params.items()))

    def is_in_cache(self, query_key):
        """Check if a query is in the cache and not expired."""
        if not self.cache_enabled or query_key not in self.query_cache:
            return False

        # Check if the cached result has expired
        _, timestamp = self.query_cache[query_key]
        if time.time() - timestamp > self.cache_ttl:
            # Remove expired entry
            del self.query_cache[query_key]
            return False

        return True

    def get_from_cache(self, query_key):
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

    def add_to_cache(self, query_key, result):
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


class MockProcessor:
    """
    Mock processor for testing the optimizer.
    """
    def __init__(self):
        """Initialize with mock entity data."""
        self.entity_info = {
            "entity1": {
                "inbound_connections": [{"id": i, "relation_type": "instance_of"} for i in range(15)],
                "outbound_connections": [{"id": i, "relation_type": "has_part"} for i in range(5)],
                "properties": {"name": "Entity 1", "popularity": "high"},
                "type": "category"
            },
            "entity2": {
                "inbound_connections": [{"id": i, "relation_type": "part_of"} for i in range(3)],
                "outbound_connections": [{"id": i, "relation_type": "related_to"} for i in range(2)],
                "properties": {"name": "Entity 2", "popularity": "medium"},
                "type": "topic"
            },
            "entity3": {
                "inbound_connections": [],
                "outbound_connections": [{"id": i, "relation_type": "similar_to"} for i in range(1)],
                "properties": {"name": "Entity 3"},
                "type": "document"
            }
        }

    def search_by_vector(self, query_vector, top_k=5, min_score=0.5):
        """Mock vector search."""
        return [{"id": f"vec_{i}", "score": 0.95 - (i * 0.05)} for i in range(top_k)]

    def expand_by_graph(self, vector_results, max_depth=2, edge_types=None):
        """Mock graph expansion."""
        results = vector_results.copy()
        for result in vector_results:
            # Add related entities
            for i in range(max_depth):
                results.append({
                    "id": f"{result['id']}_related_{i}",
                    "score": result["score"] * 0.8,
                    "relationship": edge_types[0] if edge_types else "generic"
                })
        return results

    def rank_results(self, results, vector_weight=0.7, graph_weight=0.3):
        """Mock result ranking."""
        # Sort by score
        return sorted(results, key=lambda x: x["score"], reverse=True)

    def get_entity_info(self, entity_id):
        """Mock entity info retrieval."""
        if entity_id in self.entity_info:
            return self.entity_info[entity_id]

        # Default entity data
        return {
            "inbound_connections": [{"id": i, "relation_type": "connects_to"} for i in range(2)],
            "outbound_connections": [{"id": i, "relation_type": "part_of"} for i in range(1)],
            "properties": {"name": f"Entity {entity_id}"},
            "type": "concept"
        }

    def direct_graph_query(self, query):
        """Mock direct graph query."""
        return [{"id": f"result_{i}", "score": 0.9 - (i * 0.1)} for i in range(3)]


class UnifiedGraphRAGQueryOptimizer:
    """
    Combines optimization strategies for different graph types.
    """

    def __init__(
        self,
        rewriter=None,
        budget_manager=None,
        base_optimizer=None,
        graph_info=None
    ):
        """Initialize the unified optimizer."""
        # Track traversal statistics for adaptive optimization
        self._traversal_stats = {
            "paths_explored": [],
            "path_scores": {},
            "entity_frequency": {},
            "entity_connectivity": {},
            "relation_usefulness": {}
        }

        self.rewriter = rewriter or QueryRewriter(traversal_stats=self._traversal_stats)
        self.budget_manager = budget_manager or QueryBudgetManager()
        self.base_optimizer = base_optimizer or GraphRAGQueryOptimizer()
        self.query_stats = self.base_optimizer.query_stats
        self.graph_info = graph_info or {"graph_type": "general", "graph_density": 0.2}

        # Specialized optimizers by graph type
        self._specific_optimizers = {
            "wikipedia": GraphRAGQueryOptimizer(
                query_stats=self.query_stats,
                vector_weight=0.6,
                graph_weight=0.4,
                cache_ttl=600.0,
                cache_size_limit=200
            ),
            "ipld": GraphRAGQueryOptimizer(
                query_stats=self.query_stats,
                vector_weight=0.75,
                graph_weight=0.25,
                cache_ttl=300.0
            ),
            "general": self.base_optimizer
        }

        # Cache for entity importance scores
        self._entity_importance_cache = {}

        # Performance metrics for different traversal strategies
        self._strategy_performance = {
            "breadth_first": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0},
            "depth_first": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0},
            "bidirectional": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0},
            "entity_importance": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0},
            "dag_traversal": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0}  # Add IPLD-specific traversal strategy
        }

    def detect_graph_type(self, query):
        """
        Detect the graph type from the query parameters.
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

    def calculate_entity_importance(self, entity_id, graph_processor):
        """
        Calculate the importance score of an entity in the knowledge graph.
        """
        # Check cache first
        if entity_id in self._entity_importance_cache:
            return self._entity_importance_cache[entity_id]

        # Base score
        importance = 0.5

        try:
            # Get entity information
            entity_info = graph_processor.get_entity_info(entity_id)

            if entity_info:
                # Factor 1: Connection count (normalized)
                inbound_connections = len(entity_info.get("inbound_connections", []))
                outbound_connections = len(entity_info.get("outbound_connections", []))
                total_connections = inbound_connections + outbound_connections
                connection_score = min(1.0, total_connections / 20.0)  # Normalize with a cap at 20 connections

                # Factor 2: Connection diversity (unique relation types)
                relation_types = set()
                for conn in entity_info.get("inbound_connections", []) + entity_info.get("outbound_connections", []):
                    relation_types.add(conn.get("relation_type", ""))
                diversity_score = min(1.0, len(relation_types) / 10.0)  # Normalize with a cap at 10 types

                # Factor 3: Semantic richness (properties count)
                property_count = len(entity_info.get("properties", {}))
                property_score = min(1.0, property_count / 15.0)  # Normalize with a cap at 15 properties

                # Factor 4: Entity type importance
                entity_type = entity_info.get("type", "").lower()
                type_score = 0.5  # Default
                if entity_type in ["concept", "topic", "category"]:
                    type_score = 0.9
                elif entity_type in ["person", "organization", "location"]:
                    type_score = 0.8
                elif entity_type in ["event", "work"]:
                    type_score = 0.7

                # Calculate weighted importance
                importance = (
                    connection_score * 0.4 +
                    diversity_score * 0.25 +
                    property_score * 0.15 +
                    type_score * 0.2
                )

                # Update statistics for this entity
                self._traversal_stats["entity_frequency"][entity_id] = self._traversal_stats["entity_frequency"].get(entity_id, 0) + 1
                self._traversal_stats["entity_connectivity"][entity_id] = total_connections

        except Exception as e:
            print(f"Error calculating entity importance for {entity_id}: {e}")

        # Cache the result
        self._entity_importance_cache[entity_id] = importance
        return importance

    def optimize_query(self, query, priority="normal", graph_processor=None):
        """
        Generate an optimized query plan with unified optimizations.
        """
        # Detect graph type
        graph_type = self.detect_graph_type(query)

        # Set appropriate graph info for the detected type
        if graph_type == "ipld" and self.graph_info.get("graph_type") != "ipld":
            # Use ipld-specific graph info
            graph_info = {
                "graph_type": "ipld",
                "edge_selectivity": self.graph_info.get("edge_selectivity", {}),
                "graph_density": self.graph_info.get("graph_density", 0.4)
            }
        else:
            graph_info = self.graph_info

        # Get the appropriate optimizer
        optimizer = self._specific_optimizers.get(graph_type, self.base_optimizer)

        # Calculate entity scores if graph processor is available
        entity_scores = {}
        if graph_processor and "entity_ids" in query:
            for entity_id in query["entity_ids"]:
                entity_scores[entity_id] = self.calculate_entity_importance(entity_id, graph_processor)

        # Create a deep copy of the query
        rewritten_query = query.copy()

        # Apply graph-specific optimizations first
        if graph_type == "ipld":
            rewritten_query = self.optimize_ipld_traversal(rewritten_query, entity_scores)
            print(f"DEBUG: After IPLD optimization: {rewritten_query}")
        elif graph_type == "wikipedia":
            rewritten_query = self.optimize_wikipedia_traversal(rewritten_query, entity_scores)

        # Then apply query rewriting with entity scores
        rewritten_query = self.rewriter.rewrite_query(rewritten_query, graph_info, entity_scores)

        # Special handling for IPLD-specific settings to ensure they're not overwritten
        if graph_type == "ipld":
            # Make sure traversal section exists
            if "traversal" not in rewritten_query:
                rewritten_query["traversal"] = {}

            # Ensure critical IPLD settings are not lost
            rewritten_query["traversal"]["use_cid_path_optimization"] = True
            rewritten_query["traversal"]["enable_path_caching"] = True
            rewritten_query["traversal"]["strategy"] = "dag_traversal"

        # Get specialized optimization parameters
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
            optimized_params = {"params": rewritten_query, "weights": {"vector": 0.7, "graph": 0.3}}

        # Ensure traversal parameters are copied to optimized params for IPLD
        if graph_type == "ipld" and "traversal" in rewritten_query:
            if "params" in optimized_params and "traversal" not in optimized_params["params"]:
                optimized_params["params"]["traversal"] = {}

            # Copy IPLD-specific traversal parameters
            for key, value in rewritten_query["traversal"].items():
                optimized_params["params"]["traversal"][key] = value

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
            },
            "traversal_strategy": rewritten_query.get("traversal", {}).get("strategy", "default")
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

        print(f"DEBUG: Final optimized plan for {graph_type}: {plan}")
        return plan

    def optimize_wikipedia_traversal(self, query, entity_scores):
        """
        Apply Wikipedia-specific traversal optimizations.

        Uses statistical analysis and entity importance to optimize
        traversal for Wikipedia-derived knowledge graphs.

        Args:
            query: Original query parameters
            entity_scores: Dictionary of entity importance scores

        Returns:
            Dict: Optimized query parameters
        """
        optimized_query = query.copy()

        # Wikipedia graphs have specific edge types that are most informative
        high_value_relations = [
            "instance_of", "subclass_of", "part_of", "has_part",
            "located_in", "capital_of", "creator", "developer",
            "follows", "followed_by", "opposite_of"
        ]

        # Edge types with lower information value (often too general)
        low_value_relations = [
            "related_to", "see_also", "different_from", "same_as",
            "externally_linked", "link", "described_by"
        ]

        # If edge types specified, prioritize high-value relations
        if "traversal" not in optimized_query:
            optimized_query["traversal"] = {}

        if "edge_types" in optimized_query["traversal"]:
            edge_types = optimized_query["traversal"]["edge_types"]

            # Reorder edge types by importance
            prioritized_edges = []

            # 1. Add high-value edges first
            for edge in high_value_relations:
                if edge in edge_types:
                    prioritized_edges.append(edge)

            # 2. Add other edges that aren't explicitly low-value
            for edge in edge_types:
                if edge not in prioritized_edges and edge not in low_value_relations:
                    prioritized_edges.append(edge)

            # 3. Add low-value edges last
            for edge in edge_types:
                if edge not in prioritized_edges:
                    prioritized_edges.append(edge)

            optimized_query["traversal"]["edge_types"] = prioritized_edges

        # Adaptive traversal parameters based on query complexity
        query_complexity = self._estimate_query_complexity(optimized_query)

        if query_complexity == "high":
            # For complex queries, limit breadth to avoid combinatorial explosion
            optimized_query["traversal"]["max_breadth_per_level"] = 5
            optimized_query["traversal"]["use_importance_pruning"] = True
            optimized_query["traversal"]["importance_threshold"] = 0.4
        elif query_complexity == "medium":
            # Balanced approach
            optimized_query["traversal"]["max_breadth_per_level"] = 7
            optimized_query["traversal"]["use_importance_pruning"] = True
            optimized_query["traversal"]["importance_threshold"] = 0.3

        # Set traversal strategy based on previous performance
        if self._strategy_performance["entity_importance"]["count"] > 0:
            # Get best performing strategy
            best_strategy = max(
                self._strategy_performance.items(),
                key=lambda x: x[1]["relevance_score"] if x[1]["count"] > 0 else 0
            )[0]

            optimized_query["traversal"]["strategy"] = best_strategy
        else:
            # Default to entity importance for Wikipedia
            optimized_query["traversal"]["strategy"] = "entity_importance"

        # Add entity importance scores for prioritization
        optimized_query["traversal"]["entity_scores"] = entity_scores

        # Wikipedia graphs benefit from bidirectional search for fact verification queries
        if self._detect_fact_verification_query(optimized_query):
            optimized_query["traversal"]["strategy"] = "bidirectional"
            optimized_query["traversal"]["bidirectional_entity_limit"] = 5

        # Add semantic filters for Wikipedia text fields
        if "vector_params" not in optimized_query:
            optimized_query["vector_params"] = {}

        # Add semantic match field for Wikipedia text content
        optimized_query["vector_params"]["semantic_match_fields"] = ["title", "text", "description"]

        return optimized_query

    def optimize_ipld_traversal(self, query, entity_scores):
        """
        Apply IPLD-specific traversal optimizations.

        Optimizes traversal for content-addressed IPLD graphs, focusing on
        CID-based paths and DAG structure optimization.

        Args:
            query: Original query parameters
            entity_scores: Dictionary of entity importance scores

        Returns:
            Dict: Optimized query parameters
        """
        optimized_query = query.copy()

        # IPLD-specific optimizations leverage the content-addressed nature
        if "traversal" not in optimized_query:
            optimized_query["traversal"] = {}

        traversal = optimized_query["traversal"]

        # Enable CID path optimization for IPLD
        traversal["use_cid_path_optimization"] = True

        # Enable path caching for repeated traversals through the same nodes
        traversal["enable_path_caching"] = True

        # Set traversal strategy to "dag_traversal" which is optimized for IPLD DAGs
        traversal["strategy"] = "dag_traversal"

        # DAG-level optimizations (skips redundant paths in directed acyclic graphs)
        traversal["visit_nodes_once"] = True

        # Add content-addressed DAG batching
        # Process block loading in batches by prefix for efficiency
        traversal["batch_loading"] = True
        traversal["batch_size"] = 100  # Load 100 blocks at a time
        traversal["batch_by_prefix"] = True  # Group by CID prefix for locality

        # Query complexity determines multihash verification strategy
        query_complexity = self._estimate_query_complexity(optimized_query)
        if query_complexity == "low":
            # Verify all multihashes for low complexity queries
            traversal["verify_multihashes"] = True
        else:
            # Skip verification for performance on complex queries
            traversal["verify_multihashes"] = False

        # If query involves vector search, optimize for IPLD vector indexes
        if "vector_params" not in optimized_query:
            optimized_query["vector_params"] = {}

        # Reduce feature vector dimensions for faster comparison
        optimized_query["vector_params"]["use_dimensionality_reduction"] = True

        # Set bucket optimization for content-addressed vectors
        optimized_query["vector_params"]["use_cid_bucket_optimization"] = True

        # Enable block-based batch loading for vectors
        optimized_query["vector_params"]["enable_block_batch_loading"] = True

        # Add entity scores for path prioritization
        traversal["entity_scores"] = entity_scores

        # Add IPLD-specific performance tracking
        if "dag_traversal" in self._strategy_performance:
            # If we have performance data, adjust batch size based on past performance
            perf_data = self._strategy_performance["dag_traversal"]
            if perf_data["count"] > 5:
                # If we have enough samples and performance isn't great, increase batch size
                if perf_data["avg_time"] > 1.0 and perf_data["relevance_score"] < 0.8:
                    traversal["batch_size"] = min(200, traversal["batch_size"] * 1.5)

        # Debug output to trace IPLD optimizations being applied
        print(f"DEBUG: IPLD optimizations applied to traversal: {traversal}")

        return optimized_query

    def _detect_fact_verification_query(self, query):
        """
        Detect if a query is a fact verification query.

        Args:
            query: Query parameters

        Returns:
            bool: Whether this is a fact verification query
        """
        # Check for fact verification signals
        if "verification" in str(query).lower():
            return True

        # Check for source and target entities (common in fact verification)
        if "source_entity" in query and "target_entity" in query:
            return True

        # Check for fact verification language in query text
        if "query_text" in query:
            query_text = query["query_text"].lower()
            fact_patterns = [
                "is it true that", "verify if", "check if", "is there a connection between",
                "are", "is", "did", "was", "were", "do", "does", "has", "have",
                "connected to", "related to", "linked to"
            ]

            if any(pattern in query_text for pattern in fact_patterns):
                return True

        return False

    def _estimate_query_complexity(self, query):
        """
        Estimate query complexity for optimization decisions.

        Args:
            query: Query parameters

        Returns:
            str: Complexity level ("low", "medium", "high")
        """
        complexity_score = 0

        # Check vector query complexity
        if "vector_params" in query:
            vector_params = query["vector_params"]
            complexity_score += min(5, vector_params.get("top_k", 5) * 0.5)

        # Check traversal complexity
        if "traversal" in query:
            traversal = query["traversal"]
            # Depth has exponential impact on complexity
            max_depth = traversal.get("max_depth", 2)
            complexity_score += max_depth * 2

            # Edge types increases complexity
            edge_types = traversal.get("edge_types", [])
            complexity_score += min(5, len(edge_types) * 0.5)

        # Determine complexity level
        if complexity_score < 5:
            return "low"
        elif complexity_score < 10:
            return "medium"
        else:
            return "high"

    def execute_query(
        self,
        processor,
        query,
        priority="normal",
        skip_cache=False
    ):
        """
        Execute a GraphRAG query with unified optimizations.

        Args:
            processor: GraphRAG processor implementation
            query: Query to execute
            priority: Query priority
            skip_cache: Whether to skip cache

        Returns:
            Tuple[List[Dict], Dict]: (Results, execution_info)
        """
        # Generate optimized query plan, passing the processor for advanced optimizations
        plan = self.optimize_query(query, priority, processor)
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

            # 1. Vector search phase
            vector_search_start = time.time()
            vector_params = {}

            # Copy vector search parameters
            if "vector_params" in params:
                vector_params = params["vector_params"]

            # Extract key parameters
            top_k = vector_params.get("top_k", params.get("max_vector_results", 5))
            min_score = vector_params.get("min_score", params.get("min_similarity", 0.5))

            # Execute vector search
            vector_results = processor.search_by_vector(
                query_vector,
                top_k=top_k,
                min_score=min_score
            )
            vector_search_time = (time.time() - vector_search_start) * 1000  # in ms
            self.budget_manager.track_consumption("vector_search_ms", vector_search_time)

            # Check for early stopping
            if not vector_results:
                execution_time = time.time() - start_time
                self.query_stats.record_query_time(execution_time)
                return [], {"from_cache": False, "execution_time": execution_time, "plan": plan}

            # 2. Graph traversal phase
            graph_traversal_start = time.time()

            # Extract traversal parameters
            traversal_params = {}
            if "traversal" in params:
                traversal_params = params["traversal"]

            # Extract key parameters
            max_depth = traversal_params.get("max_depth", params.get("max_traversal_depth", 2))
            edge_types = traversal_params.get("edge_types", params.get("edge_types"))

            # Select appropriate traversal method based on strategy
            traversal_strategy = traversal_params.get("strategy", "default")

            # Track which strategy is being used for performance comparison
            strategy_start_time = time.time()

            print(f"DEBUG: Using traversal strategy: {traversal_strategy} with processor: {processor.__class__.__name__}")
            print(f"DEBUG: Has expand_by_dag_traversal: {hasattr(processor, 'expand_by_dag_traversal')}")

            if traversal_strategy == "dag_traversal" and hasattr(processor, "expand_by_dag_traversal"):
                # Use DAG-optimized traversal for IPLD graphs
                try:
                    print(f"DEBUG: Executing DAG traversal with {len(vector_results)} vectors, depth={max_depth}")
                    # Try specialized method first
                    graph_results = processor.expand_by_dag_traversal(
                        vector_results,
                        max_depth=max_depth,
                        edge_types=edge_types,
                        visit_nodes_once=traversal_params.get("visit_nodes_once", True),
                        batch_loading=traversal_params.get("batch_loading", False),
                        batch_size=traversal_params.get("batch_size", 100)
                    )
                    print(f"DEBUG: DAG traversal returned {len(graph_results)} results")

                    # Verify results contain CIDs (critical for IPLD)
                    cid_results = [r for r in graph_results if "cid" in r]
                    print(f"DEBUG: Found {len(cid_results)} results with CIDs")

                    # If no results with CIDs, use standard traversal as fallback
                    if not cid_results and hasattr(processor, "expand_by_graph"):
                        print(f"WARNING: DAG traversal returned no results with CIDs, falling back to standard traversal")
                        graph_results = processor.expand_by_graph(
                            vector_results,
                            max_depth=max_depth,
                            edge_types=edge_types
                        )
                except Exception as e:
                    print(f"Warning: DAG traversal failed with error: {e}. Falling back to standard traversal.")
                    # Fall back to standard method if specialized method fails
                    if hasattr(processor, "expand_by_graph"):
                        graph_results = processor.expand_by_graph(
                            vector_results,
                            max_depth=max_depth,
                            edge_types=edge_types
                        )
                    else:
                        # If no fallback method, return vector results
                        print(f"WARNING: No fallback method available, returning vector results only")
                        graph_results = vector_results
            else:
                # Use standard graph expansion as fallback
                if hasattr(processor, "expand_by_graph"):
                    graph_results = processor.expand_by_graph(
                        vector_results,
                        max_depth=max_depth,
                        edge_types=edge_types
                    )
                else:
                    # If processor doesn't have expand_by_graph method, return vector results
                    print(f"WARNING: Processor has no expand_by_graph method, returning vector results only")
                    graph_results = vector_results

            # Track strategy performance
            strategy_time = time.time() - strategy_start_time
            if traversal_strategy in self._strategy_performance:
                perf = self._strategy_performance[traversal_strategy]
                # Update performance metrics for this strategy
                if perf["count"] > 0:
                    perf["avg_time"] = (perf["avg_time"] * perf["count"] + strategy_time) / (perf["count"] + 1)
                else:
                    perf["avg_time"] = strategy_time
                perf["count"] += 1
            graph_traversal_time = (time.time() - graph_traversal_start) * 1000  # in ms
            self.budget_manager.track_consumption("graph_traversal_ms", graph_traversal_time)

            # Check for early stopping
            consumption_report = self.budget_manager.get_current_consumption_report()
            if self.budget_manager.suggest_early_stopping(graph_results, consumption_report["overall_consumption_ratio"]):
                execution_time = time.time() - start_time
                self.query_stats.record_query_time(execution_time)
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
            combined_results = processor.direct_graph_query(query) if hasattr(processor, "direct_graph_query") else []

        # Record execution time
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


# Test classes

class TestQueryRewriter(unittest.TestCase):
    """Test the QueryRewriter functionality."""

    def setUp(self):
        """Set up test components."""
        self.rewriter = QueryRewriter()
        self.graph_info = {
            "graph_type": "general",
            "edge_selectivity": {
                "knows": 0.8,       # Less selective
                "works_for": 0.2,   # More selective
                "founded": 0.5      # Medium selectivity
            },
            "graph_density": 0.2
        }

    def test_predicate_pushdown(self):
        """Test predicate pushdown."""
        query = {
            "min_similarity": 0.75,
            "entity_filters": {
                "entity_types": ["Person", "Location"]
            }
        }

        rewritten = self.rewriter.rewrite_query(query, self.graph_info)

        # Check min_similarity was moved to vector_params
        self.assertNotIn("min_similarity", rewritten)
        self.assertIn("vector_params", rewritten)
        self.assertEqual(rewritten["vector_params"]["min_score"], 0.75)

        # Check entity_types were moved to vector_params
        self.assertNotIn("entity_filters", rewritten)
        self.assertEqual(rewritten["vector_params"]["entity_types"], ["Person", "Location"])

    def test_join_reordering(self):
        """Test join reordering based on selectivity."""
        query = {
            "traversal": {
                "edge_types": ["knows", "founded", "works_for"]  # Unordered
            }
        }

        rewritten = self.rewriter.rewrite_query(query, self.graph_info)

        # Check edge_types were reordered by selectivity
        expected_order = ["works_for", "founded", "knows"]  # From most to least selective
        self.assertEqual(rewritten["traversal"]["edge_types"], expected_order)
        self.assertTrue(rewritten["traversal"]["reordered_by_selectivity"])

    def test_pattern_specific_optimizations(self):
        """Test pattern-specific optimizations."""
        # Test entity lookup pattern
        entity_query = {"entity_id": "entity123"}
        rewritten = self.rewriter.rewrite_query(entity_query, self.graph_info)
        self.assertTrue(rewritten.get("skip_vector_search"))

        # Test relation-centric pattern
        relation_query = {"traversal": {"edge_types": ["works_for"]}}
        rewritten = self.rewriter.rewrite_query(relation_query, self.graph_info)
        self.assertTrue(rewritten["traversal"].get("prioritize_relationships"))

        # Test fact verification pattern
        fact_query = {"source_entity": "e1", "target_entity": "e2"}
        rewritten = self.rewriter.rewrite_query(fact_query, self.graph_info)
        self.assertEqual(rewritten["traversal"].get("strategy"), "path_finding")
        self.assertTrue(rewritten["traversal"].get("find_shortest_path"))

    def test_domain_specific_optimizations(self):
        """Test domain-specific optimizations."""
        # Set up Wikipedia graph info
        wiki_graph_info = {
            "graph_type": "wikipedia",
            "edge_selectivity": self.graph_info["edge_selectivity"]
        }

        query = {
            "traversal": {
                "edge_types": ["related_topic", "instance_of", "mentions", "subclass_of"]
            }
        }

        rewritten = self.rewriter.rewrite_query(query, wiki_graph_info)

        # Check edge reordering for Wikipedia
        # Priority edges should come first
        self.assertIn("instance_of", rewritten["traversal"]["edge_types"][:2])
        self.assertIn("subclass_of", rewritten["traversal"]["edge_types"][:2])

        # Check hierarchical weight
        self.assertEqual(rewritten["traversal"].get("hierarchical_weight"), 1.5)


class TestQueryBudgetManager(unittest.TestCase):
    """Test the QueryBudgetManager functionality."""

    def setUp(self):
        """Set up test components."""
        self.budget_manager = QueryBudgetManager()

    def test_budget_allocation(self):
        """Test budget allocation based on query characteristics."""
        # Simple query
        simple_query = {
            "vector_params": {"top_k": 3},
            "traversal": {"max_depth": 1}
        }

        # Complex query
        complex_query = {
            "vector_params": {"top_k": 10},
            "traversal": {
                "max_depth": 4,
                "edge_types": ["type1", "type2", "type3"]
            }
        }

        # Allocate budgets with different priorities
        simple_budget = self.budget_manager.allocate_budget(simple_query, "normal")
        complex_budget = self.budget_manager.allocate_budget(complex_query, "normal")
        complex_high_budget = self.budget_manager.allocate_budget(complex_query, "high")

        # Check that complex query gets more resources
        self.assertGreater(complex_budget["timeout_ms"], simple_budget["timeout_ms"])
        self.assertGreater(complex_budget["max_nodes"], simple_budget["max_nodes"])

        # Check that high priority gets more resources
        self.assertGreater(complex_high_budget["timeout_ms"], complex_budget["timeout_ms"])
        self.assertGreater(complex_high_budget["max_nodes"], complex_budget["max_nodes"])

    def test_consumption_tracking(self):
        """Test resource consumption tracking."""
        query = {"vector_params": {"top_k": 5}, "traversal": {"max_depth": 2}}

        # Allocate budget (initializes consumption tracking)
        budget = self.budget_manager.allocate_budget(query)

        # Track consumption
        self.budget_manager.track_consumption("vector_search_ms", 150.5)
        self.budget_manager.track_consumption("graph_traversal_ms", 450.0)
        self.budget_manager.track_consumption("nodes_visited", 350)
        self.budget_manager.track_consumption("edges_traversed", 1200)
        self.budget_manager.track_consumption("ranking_ms", 50.2)

        # Get consumption report
        report = self.budget_manager.get_current_consumption_report()

        # Verify tracked consumption
        self.assertEqual(report["vector_search_ms"], 150.5)
        self.assertEqual(report["graph_traversal_ms"], 450.0)
        self.assertEqual(report["nodes_visited"], 350)
        self.assertEqual(report["edges_traversed"], 1200)
        self.assertEqual(report["ranking_ms"], 50.2)

        # Verify ratios
        expected_ratio = 150.5 / budget["vector_search_ms"]
        self.assertAlmostEqual(report["ratios"]["vector_search_ms"], expected_ratio)

        # Record completion
        self.budget_manager.record_completion(success=True)
        self.assertEqual(len(self.budget_manager.budget_history["vector_search_ms"]), 1)
        self.assertEqual(self.budget_manager.budget_history["vector_search_ms"][0], 150.5)

    def test_early_stopping(self):
        """Test early stopping suggestions."""
        # Too few results - should not suggest stopping
        results1 = [{"score": 0.9}, {"score": 0.8}]
        self.assertFalse(self.budget_manager.suggest_early_stopping(results1, 0.8))

        # High budget consumption, high quality results - should suggest stopping
        results2 = [{"score": 0.95}, {"score": 0.92}, {"score": 0.90}, {"score": 0.8}]
        self.assertTrue(self.budget_manager.suggest_early_stopping(results2, 0.75))

        # High budget consumption, lower quality results - should not suggest stopping
        results3 = [{"score": 0.80}, {"score": 0.78}, {"score": 0.75}, {"score": 0.7}]
        self.assertFalse(self.budget_manager.suggest_early_stopping(results3, 0.75))

        # Significant diminishing returns - should suggest stopping
        results5 = [{"score": 0.9}, {"score": 0.7}, {"score": 0.65}, {"score": 0.6}, {"score": 0.55}, {"score": 0.5}]
        self.assertTrue(self.budget_manager.suggest_early_stopping(results5, 0.5))


class TestUnifiedGraphRAGQueryOptimizer(unittest.TestCase):
    """Test the UnifiedGraphRAGQueryOptimizer functionality."""

    def setUp(self):
        """Set up test components."""
        self.stats = GraphRAGQueryStats()
        self.base_optimizer = GraphRAGQueryOptimizer(query_stats=self.stats)
        self.rewriter = QueryRewriter()
        self.budget_manager = QueryBudgetManager()
        self.graph_info = {
            "graph_type": "general",
            "edge_selectivity": {
                "knows": 0.1,
                "works_for": 0.3,
                "related_to": 0.5
            },
            "graph_density": 0.2
        }
        self.unified_optimizer = UnifiedGraphRAGQueryOptimizer(
            rewriter=self.rewriter,
            budget_manager=self.budget_manager,
            base_optimizer=self.base_optimizer,
            graph_info=self.graph_info
        )

        # Mock processor
        self.processor = MockProcessor()

        # Test vector
        self.test_vector = np.random.rand(10)

    def test_optimizer_instantiation(self):
        """Test that the UnifiedGraphRAGQueryOptimizer is instantiated correctly."""
        self.assertIsNotNone(self.unified_optimizer)
        self.assertIsInstance(self.unified_optimizer.rewriter, QueryRewriter)
        self.assertIsInstance(self.unified_optimizer.budget_manager, QueryBudgetManager)
        self.assertIsInstance(self.unified_optimizer.base_optimizer, GraphRAGQueryOptimizer)
        self.assertIsInstance(self.unified_optimizer.query_stats, GraphRAGQueryStats)

    def test_optimize_query(self):
        """Test optimize_query method."""
        query = {
            "query_vector": self.test_vector,
            "max_vector_results": 5,
            "max_traversal_depth": 2,
            "edge_types": ["knows", "works_for"]
        }

        plan = self.unified_optimizer.optimize_query(query)

        # Check that the plan has the expected structure
        self.assertIn("query", plan)
        self.assertIn("weights", plan)
        self.assertIn("budget", plan)
        self.assertIn("graph_type", plan)
        self.assertIn("statistics", plan)
        self.assertIn("caching", plan)

        # Check that query parameters were passed through
        self.assertEqual(plan["query"].get("max_vector_results"), 5)
        self.assertEqual(plan["query"].get("max_traversal_depth"), 2)
        self.assertEqual(plan["query"].get("edge_types"), ["knows", "works_for"])

        # Check budget allocation
        self.assertIn("timeout_ms", plan["budget"])
        self.assertIn("max_nodes", plan["budget"])

    def test_execute_query(self):
        """Test execute_query method."""
        query = {
            "query_vector": self.test_vector,
            "max_vector_results": 3,
            "max_traversal_depth": 1
        }

        results, info = self.unified_optimizer.execute_query(self.processor, query)

        # Check that results are returned
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

        # Check that execution info is returned
        self.assertIn("from_cache", info)
        self.assertIn("execution_time", info)
        self.assertIn("plan", info)
        self.assertIn("consumption", info)

        # Verify that query stats were updated
        self.assertEqual(self.unified_optimizer.query_stats.query_count, 1)

        # Test caching
        # First execution should not be from cache
        self.assertFalse(info["from_cache"])

        # Second execution should be from cache
        results2, info2 = self.unified_optimizer.execute_query(self.processor, query)
        self.assertTrue(info2["from_cache"])

    def test_entity_importance_calculation(self):
        """Test the entity importance calculation."""
        # Check importance for entity with many connections (entity1)
        entity1_importance = self.unified_optimizer.calculate_entity_importance("entity1", self.processor)
        self.assertGreater(entity1_importance, 0.5)  # Should have high importance

        # Check importance for entity with fewer connections (entity3)
        entity3_importance = self.unified_optimizer.calculate_entity_importance("entity3", self.processor)
        self.assertLess(entity3_importance, entity1_importance)  # Should have lower importance

        # Test caching of entity importance scores
        cached_importance = self.unified_optimizer.calculate_entity_importance("entity1", self.processor)
        self.assertEqual(cached_importance, entity1_importance)  # Should return the same value from cache

        # Check that entity info is being tracked in statistics
        entity_id = "entity1"
        self.assertIn(entity_id, self.unified_optimizer._traversal_stats["entity_frequency"])
        self.assertIn(entity_id, self.unified_optimizer._traversal_stats["entity_connectivity"])


if __name__ == "__main__":
    unittest.main()
