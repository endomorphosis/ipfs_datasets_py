"""Unified GraphRAG query optimizer orchestration layer."""

from __future__ import annotations

import logging
import time
import hashlib
import json
import re
import os
import csv
import uuid
import datetime
import copy
import math
from io import StringIO
from typing import Dict, List, Any, Optional, Tuple, Callable, Union, Set, TYPE_CHECKING, Iterator
from collections import defaultdict, OrderedDict, deque
from contextlib import contextmanager

# Optional dependencies with graceful fallbacks
try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

    class MockNumpy:
        @staticmethod
        def array(x):
            return list(x) if hasattr(x, '__iter__') else [x]

        @staticmethod
        def mean(x):
            return sum(x) / len(x) if x else 0

        @staticmethod
        def std(x):
            if not x:
                return 0
            mean_val = sum(x) / len(x)
            variance = sum((val - mean_val) ** 2 for val in x) / len(x)
            return variance ** 0.5

    np = MockNumpy()

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False

    class MockPsutil:
        @staticmethod
        def virtual_memory():
            return type('Memory', (), {'percent': 50, 'available': 1000000000})()

        @staticmethod
        def cpu_percent():
            return 25.0

        class Process:
            def memory_info(self):
                return type('MemInfo', (), {'rss': 0, 'vms': 0})()

            def cpu_percent(self):
                return 0.0

    psutil = MockPsutil()

# Optional visualization dependencies
if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from matplotlib.axes import Axes
else:
    class Figure:  # pragma: no cover
        pass

    class Axes:  # pragma: no cover
        pass

try:
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors
    import networkx as nx
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    Figure = Any

# Optional LLM GraphRAG dependencies
try:
    from ipfs_datasets_py.ml.llm.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
    from ipfs_datasets_py.ml.llm.llm_graphrag import GraphRAGLLMProcessor
    LLM_GRAPHRAG_AVAILABLE = True
except ImportError:
    WikipediaKnowledgeGraphTracer = None  # type: ignore[assignment]
    GraphRAGLLMProcessor = None  # type: ignore[assignment]
    LLM_GRAPHRAG_AVAILABLE = False

# Optional wikipedia-specific optimizers
try:
    from ipfs_datasets_py.optimizers.graphrag.wikipedia_optimizer import (
        detect_graph_type,
        create_appropriate_optimizer,
        optimize_wikipedia_query,
        UnifiedWikipediaGraphRAGQueryOptimizer,
    )
    WIKIPEDIA_OPTIMIZER_AVAILABLE = True
except ImportError:
    WIKIPEDIA_OPTIMIZER_AVAILABLE = False

from ipfs_datasets_py.optimizers.graphrag.query_metrics import QueryMetricsCollector
from ipfs_datasets_py.optimizers.graphrag.query_stats import GraphRAGQueryStats
from ipfs_datasets_py.optimizers.graphrag.query_planner import GraphRAGQueryOptimizer
from ipfs_datasets_py.optimizers.graphrag.query_rewriter import QueryRewriter
from ipfs_datasets_py.optimizers.graphrag.query_budget import QueryBudgetManager
from ipfs_datasets_py.optimizers.graphrag.query_visualizer import QueryVisualizer


class UnifiedGraphRAGQueryOptimizer:
    """
    Combines optimization strategies for different graph types.
    
    Features:
    - Auto-detection of graph type from query parameters
    - Wikipedia-specific and IPLD-specific optimizations
    - Cross-graph query planning for heterogeneous environments
    - Comprehensive performance analysis and recommendation generation
    - Integration with advanced rewriting and budget management
    - Optimized traversal strategies for complex graph relationships
    - Adaptive query execution based on graph characteristics
    - Statistical optimization for Wikipedia-derived knowledge graphs
    - Dynamic prioritization of semantically important paths
    - Entity importance-based traversal optimization
    """
    
    def __init__(self, 
                 rewriter: Optional[QueryRewriter] = None,
                 budget_manager: Optional[QueryBudgetManager] = None,
                 base_optimizer: Optional[GraphRAGQueryOptimizer] = None,
                 graph_info: Optional[Dict[str, Any]] = None,
                 metrics_collector: Optional["QueryMetricsCollector"] = None,
                 visualizer: Optional["QueryVisualizer"] = None,
                 metrics_dir: Optional[str] = None):
        """
        Initialize the unified optimizer.
        
        Args:
            rewriter (QueryRewriter, optional): Query rewriter
            budget_manager (QueryBudgetManager, optional): Query budget manager
            base_optimizer (GraphRAGQueryOptimizer, optional): Base query optimizer
            graph_info (Dict, optional): Graph information for optimizations
            metrics_collector (QueryMetricsCollector, optional): Metrics collector for detailed metrics
            visualizer (QueryVisualizer, optional): Query visualizer for performance visualization
            metrics_dir (str, optional): Directory to store metrics data
        """
        # Track traversal statistics for adaptive optimization
        self._traversal_stats = {
            "paths_explored": [],
            "path_scores": {},
            "entity_frequency": defaultdict(int),
            "entity_connectivity": {},
            "relation_usefulness": defaultdict(float)
        }
        
        # Create rewriter with traversal statistics (pass stats reference)
        self.rewriter = rewriter or QueryRewriter(traversal_stats=self._traversal_stats)
        self.budget_manager = budget_manager or QueryBudgetManager()
        self.base_optimizer = base_optimizer or GraphRAGQueryOptimizer()
        self.graph_info = graph_info or {}
        self.query_stats = self.base_optimizer.query_stats
        
        # Specialized optimizers by graph type
        self._specific_optimizers = {}
        self._setup_specific_optimizers()
        
        # Cache for entity importance scores (used in Wikipedia graph optimization)
        self._entity_importance_cache: Dict[str, float] = {}
        
        # Performance metrics for different traversal strategies
        self._strategy_performance = {
            "breadth_first": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0},
            "depth_first": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0},
            "bidirectional": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0},
            "entity_importance": {"avg_time": 0.0, "relevance_score": 0.0, "count": 0}
        }
        
        # Initialize metrics collection and visualization
        if metrics_collector is None:
            self.metrics_collector = QueryMetricsCollector(
                metrics_dir=metrics_dir
            )
        else:
            self.metrics_collector = metrics_collector
            
        # Initialize visualizer if visualization is available
        self.visualizer = visualizer
        if visualizer is None and VISUALIZATION_AVAILABLE:
            self.visualizer = QueryVisualizer(self.metrics_collector)
            
        # Track last query for convenience
        self.last_query_id = None
    
    def _setup_specific_optimizers(self) -> None:
        """Set up specialized optimizers for different graph types."""
        # Wikipedia-specific optimizer with enhanced parameters
        wiki_optimizer = GraphRAGQueryOptimizer(
            query_stats=self.query_stats,
            vector_weight=0.6,     # Wikipedia weight adjustment
            graph_weight=0.4,      # Focus more on graph structure in Wikipedia
            cache_ttl=600.0,       # Longer cache for Wikipedia queries
            cache_size_limit=200   # Larger cache for Wikipedia queries
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
    
    def _create_fallback_plan(self, query: Dict[str, Any], priority: str = "normal", error: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a fallback query plan when optimization fails.
        
        Args:
            query (Dict): Original query
            priority (str): Query priority
            error (str, optional): Error message if applicable
            
        Returns:
            Dict: Fallback query plan with conservative parameters
        """
        # Create a safe copy of the query with defaults
        fallback_query = query.copy()
        
        # Ensure traversal section exists
        if "traversal" not in fallback_query:
            fallback_query["traversal"] = {}
            
        # Set conservative defaults for traversal
        if "max_depth" not in fallback_query["traversal"]:
            fallback_query["traversal"]["max_depth"] = 2
            
        # Set conservative defaults for vector search
        if "max_vector_results" not in fallback_query:
            fallback_query["max_vector_results"] = 5
            
        if "min_similarity" not in fallback_query:
            fallback_query["min_similarity"] = 0.6
        
        # Allocate a conservative budget
        budget = {
            "vector_search_ms": 500,
            "graph_traversal_ms": 1000,
            "ranking_ms": 100,
            "max_nodes": 100
        }
        
        # Try to use the budget manager if available
        if hasattr(self, 'budget_manager') and self.budget_manager is not None:
            try:
                budget = self.budget_manager.allocate_budget(fallback_query, priority)
            except Exception as e:
                # Use default budget if budget_manager fails
                pass
        
        # Return the fallback plan
        return {
            "query": fallback_query,
            "weights": {"vector": 0.7, "graph": 0.3},  # Conservative default weights
            "budget": budget,
            "graph_type": "generic",
            "statistics": {
                "fallback": True,
                "error_handled": True
            },
            "caching": {"enabled": False},  # Disable caching for fallback plans
            "traversal_strategy": "default",
            "fallback": True,
            "error": error
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
        
    def calculate_entity_importance(self, entity_id: str, graph_processor: Any) -> float:
        """
        Calculate the importance score of an entity in the knowledge graph.
        
        Uses various metrics like centrality, inbound/outbound connections,
        and semantic richness to determine entity importance for traversal.
        
        Args:
            entity_id: ID of the entity to evaluate
            graph_processor: GraphRAG processor with graph access
            
        Returns:
            float: Importance score (0.0-1.0)
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
                self._traversal_stats["entity_frequency"][entity_id] += 1
                self._traversal_stats["entity_connectivity"][entity_id] = total_connections
        
        except Exception as e:
            logging.warning(f"Error calculating entity importance for {entity_id}: {e}")
        
        # Cache the result
        self._entity_importance_cache[entity_id] = importance
        return importance
    
    def optimize_wikipedia_traversal(self, query: Dict[str, Any], entity_scores: Dict[str, float]) -> Dict[str, Any]:
        """
        Apply Wikipedia-specific traversal optimizations.
        
        Uses statistical analysis and entity importance to optimize
        traversal for Wikipedia-derived knowledge graphs. Implements advanced
        strategies for graph exploration based on Wikipedia's knowledge structure
        and relationship types.
        
        Args:
            query: Original query parameters
            entity_scores: Dictionary of entity importance scores
            
        Returns:
            Dict: Optimized query parameters
        """
        optimized_query = query.copy()
        
        # Ensure traversal section exists
        if "traversal" not in optimized_query:
            optimized_query["traversal"] = {}
            
        traversal = optimized_query["traversal"]
        
        # Get query text and complexity for adaptive optimization
        query_text = query.get("query_text", "")
        query_complexity = self._estimate_query_complexity(optimized_query)
        
        # Enhanced Wikipedia relation hierarchy with importance scores
        relation_importance = {
            # Taxonomic relationships - highest value (0.9+)
            "instance_of": 0.95,
            "subclass_of": 0.92,
            "type_of": 0.90,
            "category": 0.90,
            
            # Compositional relationships - high value (0.8+)
            "part_of": 0.88,
            "has_part": 0.85,
            "contains": 0.85,
            "component_of": 0.83,
            "member_of": 0.82,
            "has_member": 0.82,
            
            # Spatial relationships - high value (0.7+)
            "located_in": 0.79,
            "capital_of": 0.78,
            "headquarters_in": 0.78,
            "geographical_location": 0.75,
            "neighbor_of": 0.72,
            
            # Causal and temporal relationships - medium-high value (0.6+)
            "created_by": 0.69,
            "developer": 0.68,
            "author": 0.67,
            "invented_by": 0.65,
            "founder": 0.65,
            "preceded_by": 0.62,
            "followed_by": 0.62,
            "influenced": 0.60,
            
            # Functional relationships - medium value (0.5+)
            "function": 0.58,
            "used_for": 0.57,
            "works_on": 0.55,
            "employed_by": 0.55,
            "opposite_of": 0.53,
            "similar_to": 0.52,
            
            # General associative relationships - lower value (0.4+)
            "related_to": 0.45,
            "associated_with": 0.42,
            "see_also": 0.40,
            
            # Weak relationships - lowest value (<0.4)
            "different_from": 0.35,
            "same_as": 0.35,
            "externally_linked": 0.32,
            "link": 0.30,
            "described_by": 0.30
        }
        
        # Extract relation types from user query when possible
        query_relations = []
        
        # Look for relationship indicators in query
        if query_text:
            query_text_lower = query_text.lower()
            
            # Example relation detection patterns
            if any(term in query_text_lower for term in ["type", "instance", "is a", "example of"]):
                query_relations.append("instance_of")
                
            if any(term in query_text_lower for term in ["part", "component", "contain", "within", "inside"]):
                query_relations.append("part_of")
                
            if any(term in query_text_lower for term in ["located", "where", "place", "location"]):
                query_relations.append("located_in")
                
            if any(term in query_text_lower for term in ["created", "made", "developed", "authored", "wrote"]):
                query_relations.append("created_by")
                
            if any(term in query_text_lower for term in ["similar", "like", "analogous"]):
                query_relations.append("similar_to")
        
        # Add detected relations to traversal for prioritization
        if query_relations:
            traversal["detected_relations"] = query_relations
        
        # If edge types are specified in the query, reorder them by importance
        if "edge_types" in traversal:
            edge_types = traversal["edge_types"]
            
            # Create a scoring function for edge types
            def get_edge_score(edge_type):
                # Detected relations get highest priority
                if query_relations and edge_type in query_relations:
                    return 1.0 + relation_importance.get(edge_type, 0.5)
                # Otherwise use relation importance scores
                return relation_importance.get(edge_type, 0.5)
            
            # Reorder edges based on scores
            prioritized_edges = sorted(edge_types, key=get_edge_score, reverse=True)
            traversal["edge_types"] = prioritized_edges
            traversal["edge_reordered_by_importance"] = True
            
            # Store edge scores for weighted traversal
            traversal["edge_importance_scores"] = {
                edge: get_edge_score(edge) for edge in edge_types
            }
            
        # Set hierarchical relationship weighting
        traversal["hierarchical_weight"] = 1.5  # Boost hierarchical relationships
        
        # Adaptive traversal parameters based on query complexity
        if query_complexity == "high":
            # For complex queries, limit breadth to avoid combinatorial explosion
            traversal["max_breadth_per_level"] = 5
            traversal["use_importance_pruning"] = True
            traversal["importance_threshold"] = 0.4
            traversal["max_traversal_time"] = 5000  # 5 seconds max
            traversal["early_stopping_enabled"] = True
            traversal["pruning_strategy"] = "aggressive"
            
        elif query_complexity == "medium":
            # Balanced approach
            traversal["max_breadth_per_level"] = 7
            traversal["use_importance_pruning"] = True
            traversal["importance_threshold"] = 0.3
            traversal["max_traversal_time"] = 8000  # 8 seconds max
            traversal["early_stopping_enabled"] = True
            traversal["pruning_strategy"] = "balanced"
            
        else:  # Low complexity
            # More exhaustive traversal for simple queries
            traversal["max_breadth_per_level"] = 10
            traversal["use_importance_pruning"] = False
            traversal["max_traversal_time"] = 10000  # 10 seconds max
            traversal["pruning_strategy"] = "minimal"
        
        # Set traversal strategy based on query type and previous performance
        if self._detect_fact_verification_query(query):
            # Fact verification benefits from bidirectional search
            traversal["strategy"] = "bidirectional"
            traversal["bidirectional_entity_limit"] = 5
            traversal["path_finding_algorithm"] = "astar"  # A* algorithm for path finding
            traversal["use_heuristic_distance"] = True
            
        elif query_relations and ("instance_of" in query_relations or "subclass_of" in query_relations):
            # Taxonomic queries benefit from hierarchical traversal
            traversal["strategy"] = "hierarchical"
            traversal["hierarchy_direction"] = "both"  # Traverse both up and down
            traversal["max_hierarchy_depth"] = 5
            
        elif query.get("entity_ids", []) and len(query.get("entity_ids", [])) > 1:
            # Multi-entity queries benefit from entity connection finding
            traversal["strategy"] = "entity_connection"
            traversal["min_connection_confidence"] = 0.7
            traversal["max_path_length"] = 3
            
        # Use performance data if available, otherwise use heuristics
        elif self._strategy_performance["entity_importance"]["count"] > 0:
            # Get best performing strategy based on historical data
            best_strategy = max(
                self._strategy_performance.items(),
                key=lambda x: x[1]["relevance_score"] if x[1]["count"] > 0 else 0
            )[0]
            
            traversal["strategy"] = best_strategy
            traversal["strategy_selection_method"] = "performance_based"
        else:
            # Default to entity importance for Wikipedia
            traversal["strategy"] = "entity_importance"
            traversal["strategy_selection_method"] = "default"
            
        # Add entity importance scores for prioritization
        traversal["entity_scores"] = entity_scores
        
        # Add entity type awareness for targeted traversal
        entity_types = self._detect_entity_types(query_text)
        if entity_types:
            traversal["target_entity_types"] = entity_types
            
            # Type-specific traversal optimizations
            if "person" in entity_types:
                # Person-specific edge priorities for person-related queries
                traversal["person_edge_boost"] = ["created_by", "author", "founder", "member_of"]
                
            if "location" in entity_types:
                # Location-specific edge priorities
                traversal["location_edge_boost"] = ["located_in", "capital_of", "geographical_location"]
                
            if "organization" in entity_types:
                # Organization-specific edge priorities
                traversal["organization_edge_boost"] = ["has_member", "founded_by", "headquarters_in"]
                
            if "concept" in entity_types:
                # Concept-specific edge priorities
                traversal["concept_edge_boost"] = ["instance_of", "subclass_of", "related_to"]
        
        # Enhance vector search with Wikipedia-specific optimizations
        if "vector_params" in optimized_query:
            vector_params = optimized_query.get("vector_params", {})
            
            # Add semantic match fields for Wikipedia text content
            vector_params["semantic_match_fields"] = ["title", "text", "description", "summary"]
            
            # Field-specific weights for relevance scoring
            vector_params["field_weights"] = {
                "title": 1.5,      # Title matches are more important
                "text": 1.0,       # Main text has standard weight
                "description": 1.2, # Description is more important than text but less than title
                "summary": 1.3      # Summary is highly relevant
            }
            
            # Wikipedia-specific vector search enhancements
            vector_params["wikipedia_enhancements"] = {
                "boost_exact_title_match": 2.0,    # Boost exact title matches
                "boost_category_match": 1.3,       # Boost category matches
                "boost_infobox_match": 1.4,        # Boost infobox content matches
                "use_redirect_resolution": True,   # Follow Wikipedia redirects
                "use_disambiguation_handling": True, # Handle disambiguation pages
                "entity_popularity_boost": True     # Consider entity popularity
            }
            
            optimized_query["vector_params"] = vector_params
        
        # Wikipedia-specific advanced traversal options
        traversal["wikipedia_traversal_options"] = {
            "follow_redirects": True,            # Follow Wikipedia redirects during traversal
            "resolve_disambiguation": True,      # Handle disambiguation pages specially
            "use_category_hierarchy": True,      # Leverage Wikipedia category hierarchy
            "include_infobox_data": True,        # Include structured infobox data
            "cross_language_links": False,       # Skip cross-language links by default
            "confidence_weighting": True,        # Weight edges by confidence
            "popularity_bias": 0.3,              # Consider article popularity (0.0-1.0)
            "recency_bias": 0.2,                 # Consider article recency (0.0-1.0)
            "reference_count_boost": True,       # Boost well-referenced content
            "trusted_source_boost": True,        # Boost content from trusted sources
            "quality_class_awareness": True      # Consider Wikipedia quality classifications
        }
        
        # Add structured data extraction options for Wikipedia
        traversal["structured_data_extraction"] = {
            "extract_infoboxes": True,           # Extract infobox structured data
            "extract_tables": True,              # Extract table data
            "extract_lists": True,               # Extract list data
            "extract_citations": True,           # Extract citation data
            "data_quality_threshold": 0.7        # Minimum quality threshold for extraction
        }
        
        # Advanced query-aware traversal pruning
        query_keywords = set()
        if query_text:
            # Extract simple keywords from query (a real implementation would use NLP)
            query_keywords = set(query_text.lower().split())
            traversal["query_keywords"] = list(query_keywords)
            traversal["keyword_guided_pruning"] = True
            traversal["keyword_match_threshold"] = 0.3  # At least 30% keyword match
        
        return optimized_query
        
    def optimize_ipld_traversal(self, query: Dict[str, Any], entity_scores: Dict[str, float]) -> Dict[str, Any]:
        """
        Apply IPLD-specific traversal optimizations.
        
        Optimizes traversal for content-addressed IPLD graphs, focusing on 
        CID-based paths and DAG structure optimization. Implements advanced strategies for
        efficient traversal of IPLD DAGs, vector search optimization, and content-type
        specific enhancements.
        
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
        
        # Get query complexity to adapt strategies
        query_complexity = self._estimate_query_complexity(optimized_query)
        max_depth = traversal.get("max_depth", 2)
        
        # Set fundamental IPLD optimizations
        traversal["use_cid_path_optimization"] = True
        traversal["enable_path_caching"] = True
        
        # Set appropriate traversal strategy based on complexity and depth
        if max_depth >= 4 or query_complexity == "high":
            traversal["strategy"] = "dag_traversal"
            traversal["recursive_dag_descent"] = True
            traversal["max_recursion_depth"] = max_depth
            # Add prefetching for deep traversals
            traversal["prefetch_strategy"] = "predict_path"
            traversal["prefetch_depth"] = min(2, max_depth - 1)
        elif self._detect_fact_verification_query(query):
            # For fact verification, bidirectional search works better
            traversal["strategy"] = "bidirectional"
            traversal["bidirectional_max_nodes"] = 50
            traversal["search_target_matches"] = True
        else:
            # For standard queries, use optimized traversal
            traversal["strategy"] = "ipld_optimized"
            traversal["use_heuristic_expansion"] = True
        
        # DAG structural optimizations 
        traversal["visit_nodes_once"] = True
        traversal["detect_cycles"] = True
        traversal["cycle_handling"] = "prune"
        
        # IPLD-specific DAG optimization
        traversal["ipld_dag_optimizations"] = {
            "skip_redundant_traversals": True,
            "path_based_pruning": True,
            "parent_reference_handling": "skip",  # Skip traversal of parent references to avoid cycles
            "terminal_node_detection": True  # Detect and optimize handling of terminal nodes
        }
        
        # Content-addressed block loading optimizations
        traversal["batch_loading"] = True
        traversal["batch_size"] = 50 if query_complexity == "high" else 100  # Smaller batches for complex queries
        traversal["batch_by_prefix"] = True  # Group by CID prefix for locality
        traversal["dynamic_batch_sizing"] = True  # Adjust batch size based on performance
        
        # Advanced link traversal strategy
        traversal["link_traversal_strategy"] = {
            "prioritize_named_links": True,  # Prioritize links with names
            "order_links_by_name_relevance": True,  # Order links by name relevance to query
            "skip_duplicate_targets": True,  # Skip links pointing to already visited nodes
            "max_links_per_node": 200,  # Limit maximum links to traverse per node
            "link_priority_by_size": True  # Prioritize smaller blocks first for faster exploration
        }
        
        # Query complexity determines multihash verification and other optimizations
        if query_complexity == "low":
            # Full verification for low complexity queries
            traversal["verify_multihashes"] = True
            traversal["full_validation"] = True
        else:
            # Skip verification for performance on complex queries
            traversal["verify_multihashes"] = False
            traversal["validation_level"] = "minimal"
            
            # Add aggressive path pruning for high complexity queries
            if query_complexity == "high":
                traversal["aggressive_path_pruning"] = True
                traversal["max_branches_per_level"] = 7
                traversal["prune_low_score_paths"] = True
                traversal["path_score_threshold"] = 0.4
        
        # Vector search optimizations for IPLD structures
        if "vector_params" in optimized_query:
            vector_params = optimized_query["vector_params"]
            
            # Advanced dimensionality reduction
            vector_params["use_dimensionality_reduction"] = True
            vector_params["reduction_technique"] = "pca"  # Use PCA for dimension reduction
            vector_params["target_dimension"] = min(384, vector_params.get("original_dimension", 768))
            
            # Content-addressed vector optimizations
            vector_params["use_cid_bucket_optimization"] = True
            vector_params["bucket_count"] = 32  # Increase bucket count for more granular partitioning
            vector_params["adaptive_bucketing"] = True  # Adjust bucket strategy based on data distribution
            
            # Block-based vector loading optimizations
            vector_params["enable_block_batch_loading"] = True
            vector_params["vector_block_size"] = 1000  # Process vectors in blocks of 1000
            vector_params["vector_cache_strategy"] = "lru"  # Least recently used caching strategy
            vector_params["vector_cache_size"] = 10000  # Cache up to 10,000 vectors
            
            # Query-specific vector optimizations
            vector_params["adapt_precision_to_query"] = True  # Adjust precision based on query needs
            if query_complexity == "high":
                vector_params["approximate_search"] = True  # Use approximate search for complex queries
                vector_params["search_recall_target"] = 0.95  # Target 95% recall for speed
            else:
                vector_params["approximate_search"] = False  # Use exact search for simple queries
            
            # Optimize for specific vector storage patterns in IPLD
            vector_params["ipld_vector_optimizations"] = {
                "block_based_retrieval": True,
                "metadata_first_loading": True,  # Load metadata before vectors for filtering
                "lazy_vector_loading": True,  # Only load vectors when needed
                "cid_based_filtering": True,  # Filter by CID patterns before loading
                "separate_metadata_blocks": True  # Handle metadata and vector data separately
            }
            
            optimized_query["vector_params"] = vector_params
        
        # Content-type specific optimizations
        content_types = query.get("content_types", [])
        
        if any(ct for ct in content_types if "application/json" in ct or "application/dag-pb" in ct):
            # Add structured traversal optimizations for JSON or DAG-PB content
            traversal["structured_content_traversal"] = {
                "follow_schema": True,
                "prioritize_matching_properties": True,
                "schema_aware_expansion": True,
                "property_name_matching": True,
                "json_path_query_enabled": True
            }
        
        if any(ct for ct in content_types if "text/" in ct):
            # Add text-specific optimizations
            traversal["text_content_traversal"] = {
                "keyword_guided_expansion": True,
                "semantic_similarity_boost": 1.5,
                "text_block_chunking": True,
                "chunk_size": 512
            }
        
        if any(ct for ct in content_types if "application/car" in ct):
            # Add CAR-specific optimizations
            traversal["car_file_optimizations"] = {
                "indexed_retrieval": True,
                "streaming_extraction": True,
                "header_first_parsing": True,
                "selective_block_loading": True
            }
        
        # Add entity scores for path prioritization
        traversal["entity_scores"] = entity_scores
        
        # Enhanced IPLD path optimization for CID traversal
        traversal["cid_path_optimizations"] = {
            "use_path_prediction": True,  # Predict likely paths based on access patterns
            "path_compression": True,  # Use path compression to optimize traversal
            "common_prefix_optimization": True,  # Group operations by common CID prefixes
            "hop_reduction": True,  # Reduce unnecessary hops in paths when possible
            "cid_locality_awareness": True  # Leverage CID locality in storage
        }
        
        return optimized_query
        
    def optimize_traversal_path(self, 
                               query: Dict[str, Any], 
                               graph_processor: Any = None) -> Dict[str, Any]:
        """
        Optimize the graph traversal path based on graph characteristics.
        
        Uses graph-specific knowledge and past traversal statistics to
        optimize the traversal path for better performance.
        
        Args:
            query: Original query parameters
            graph_processor: GraphRAG processor (optional)
            
        Returns:
            Dict: Optimized query parameters
        """
        graph_type = self.detect_graph_type(query)
        optimized_query = query.copy()
        
        # Entity scores dictionary
        entity_scores = {}
        
        # Calculate importance for entities in the query if processor available
        if graph_processor and "entity_ids" in query:
            for entity_id in query["entity_ids"]:
                entity_scores[entity_id] = self.calculate_entity_importance(entity_id, graph_processor)
                
        # Apply graph-specific optimizations
        if graph_type == "wikipedia":
            # Use Wikipedia-specific traversal optimization
            return self.optimize_wikipedia_traversal(optimized_query, entity_scores)
        elif graph_type == "ipld":
            return self.optimize_ipld_traversal(optimized_query, entity_scores)
        
        # Generic optimization for other graph types
        if "traversal" in optimized_query:
            traversal = optimized_query["traversal"]
            
            # Basic optimization on traversal depth based on performance data
            if self.query_stats.query_count > 10:
                avg_time = self.query_stats.avg_query_time
                max_depth = traversal.get("max_depth", 2)
                
                if avg_time > 1.0 and max_depth > 2:
                    traversal["max_depth"] = max_depth - 1
                elif avg_time < 0.2 and max_depth < 3:
                    traversal["max_depth"] = max_depth + 1
            
            # Add entity scores for prioritization
            if entity_scores:
                traversal["entity_scores"] = entity_scores
                
        return optimized_query
    
    def _optimize_wikipedia_fact_verification(self, query: Dict[str, Any], traversal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Specialized optimization for Wikipedia fact verification queries.
        
        Args:
            query: The original query
            traversal: The current traversal parameters
            
        Returns:
            Dict: Enhanced traversal parameters for fact verification
        """
        # Start with bidirectional search strategy
        traversal["strategy"] = "bidirectional"
        traversal["bidirectional_entity_limit"] = 5
        traversal["path_ranking"] = "shortest_first"
        
        # Add Wikidata integration for fact verification
        traversal["wikidata_fact_verification"] = True
        traversal["validation_threshold"] = 0.7
        
        # Add fact-specific optimization parameters
        traversal["fact_verification"] = {
            "find_all_paths": True,         # Find all possible supporting/contradicting paths
            "check_contradictions": True,   # Look for contradicting evidence
            "require_references": True,     # Prioritize paths with reference citations
            "source_credibility": True,     # Consider source credibility in Wikipedia references
            "infobox_priority": True,       # Prioritize structured infobox data (higher reliability)
            "confidence_scoring": True      # Calculate confidence scores for verified facts
        }
        
        # Add source and target entity handling
        if "source_entity" in query and "target_entity" in query:
            traversal["source_entity"] = query["source_entity"]
            traversal["target_entity"] = query["target_entity"]
            traversal["relation_detection"] = True  # Detect specific relationship type
        
        # Extract expected relationship if present in query
        if "query_text" in query:
            query_text = query["query_text"].lower()
            
            # Common relationship patterns
            relationships = {
                "creator": ["create", "author", "write", "develop", "found", "invent"],
                "part_of": ["part of", "belong to", "member of", "within", "inside"],
                "temporal": ["before", "after", "during", "when", "date", "year"],
                "causal": ["cause", "result in", "lead to", "effect", "affect", "impact"],
                "spatial": ["location", "where", "place", "near", "far", "distance"]
            }
            
            # Detect relationship hints in query
            for rel_type, patterns in relationships.items():
                if any(pattern in query_text for pattern in patterns):
                    traversal["expected_relationship"] = rel_type
                    # Prioritize this relationship type in traversal
                    traversal["relationship_priority"] = rel_type
                    break
        
        # Add citation analysis
        traversal["citation_analysis"] = {
            "min_citations": 2,                  # Require at least 2 citations for high confidence
            "citation_recency_boost": True,      # Boost more recent citations
            "cross_reference_validation": True,  # Validate across multiple references
            "citation_quality_check": True       # Consider citation source quality
        }
        
        return traversal
    
    def _detect_fact_verification_query(self, query: Dict[str, Any]) -> bool:
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
                "connected to", "related to", "linked to", "correct that", "accurate that",
                "prove", "disprove", "evidence for", "support for", "refute"
            ]
            
            # Check for question format typical in fact verification
            if any(query_text.startswith(word) for word in ["is", "are", "was", "were", "do", "does", "did", "has", "have", "can", "could", "should", "would"]):
                return True
                
            # Check for fact verification keywords
            if any(pattern in query_text for pattern in fact_patterns):
                return True
                
            # Check for comparison patterns
            comparison_patterns = ["same as", "different from", "equivalent to", "similar to", "unlike"]
            if any(pattern in query_text for pattern in comparison_patterns):
                return True
                
        return False
                
    def _detect_exploratory_query(self, query: Dict[str, Any]) -> bool:
        """
        Detect if a query is an exploratory or discovery query.
        
        Identifies queries that aim to broadly explore a topic rather than 
        verify specific facts or retrieve narrowly defined information.
        These queries benefit from breadth-first traversal strategies.
        
        Args:
            query: Query parameters
            
        Returns:
            bool: Whether this is an exploratory query
        """
        # Check for explicit exploration signals in query parameters
        if any(term in str(query).lower() for term in ["exploration", "discover", "survey", "overview"]):
            return True
            
        # Check for exploratory language in query text
        if "query_text" in query:
            query_text = query["query_text"].lower()
            exploratory_patterns = [
                "what are", "tell me about", "explain", "describe", "overview of",
                "introduction to", "discover", "explore", "information about",
                "learn about", "show me", "find", "search for", "list", "examples of",
                "types of", "kinds of", "ways to", "methods of", "approaches to"
            ]
            
            if any(pattern in query_text for pattern in exploratory_patterns):
                return True
            
            # Check for broad topic indicators
            if query_text.startswith(("what", "how", "why")) and len(query_text.split()) < 6:
                # Short, open-ended questions are often exploratory
                return True
                
        # Check for high max_depth without specific target constraints
        if "traversal" in query and query["traversal"].get("max_depth", 0) > 3:
            # Deep traversal without specific target constraints often indicates exploration
            if "target_entity" not in query and "entity_ids" not in query:
                return True
                
        # Check for broad vector search parameters
        if "vector_params" in query and query["vector_params"].get("top_k", 0) > 10:
            # Retrieving many vector matches suggests exploration rather than specific lookup
            return True
                
        return False
        
    def _detect_entity_types(self, query_text: str, predefined_types: List[str] = None) -> List[str]:
        """
        Detect likely entity types from query text.
        
        Analyzes query text to identify what types of entities the query is likely to involve.
        This helps optimize traversal strategies for specific entity types.
        
        Args:
            query_text: The query text to analyze
            predefined_types: Optional list of predefined entity types to use instead of detection
            
        Returns:
            List[str]: Detected entity types
        """
        # If predefined types are provided, use those
        if predefined_types:
            return predefined_types
            
        # Default to empty list if no query text
        if not query_text:
            return []
            
        # Normalize query text
        text = query_text.lower()
        detected_types = []
        
        # Person detection patterns
        person_patterns = [
            "who", "person", "people", "author", "writer", "creator", "founder",
            "born", "died", "age", "biography", "invented", "discovered",
            "president", "king", "queen", "actor", "actress", "director",
            "scientist", "artist", "musician", "politician", "athlete"
        ]
        
        # Organization detection patterns
        organization_patterns = [
            "company", "organization", "corporation", "business", "firm", "agency", 
            "university", "school", "college", "institution", "government", "team",
            "founded", "headquarters", "ceo", "employees", "products", "services"
        ]
        
        # Location detection patterns
        location_patterns = [
            "where", "place", "location", "country", "city", "state", "region", 
            "continent", "area", "located", "capital", "geography", "landmark",
            "mountain", "river", "ocean", "lake", "island", "territory", "border"
        ]
        
        # Concept detection patterns
        concept_patterns = [
            "what", "concept", "theory", "idea", "principle", "definition",
            "meaning", "philosophy", "method", "system", "field", "discipline",
            "explain", "describe", "define", "understand", "how does", "how is"
        ]
        
        # Event detection patterns
        event_patterns = [
            "when", "event", "happened", "occurred", "took place", "date",
            "history", "war", "battle", "conference", "meeting", "election",
            "ceremony", "festival", "disaster", "revolution", "movement"
        ]
        
        # Product detection patterns
        product_patterns = [
            "product", "device", "technology", "tool", "software", "hardware",
            "machine", "vehicle", "book", "album", "movie", "film", "game",
            "service", "brand", "model", "version", "release", "launched"
        ]
        
        # Check for patterns in query
        if any(pattern in text for pattern in person_patterns):
            detected_types.append("person")
            
        if any(pattern in text for pattern in organization_patterns):
            detected_types.append("organization")
            
        if any(pattern in text for pattern in location_patterns):
            detected_types.append("location")
            
        if any(pattern in text for pattern in concept_patterns):
            detected_types.append("concept")
            
        if any(pattern in text for pattern in event_patterns):
            detected_types.append("event")
            
        if any(pattern in text for pattern in product_patterns):
            detected_types.append("product")
            
        # If no types detected, default to concept (most general)
        if not detected_types:
            detected_types.append("concept")
            
        return detected_types
    
    def _estimate_query_complexity(self, query: Dict[str, Any]) -> str:
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
            
        # Query text complexity (if present)
        if "query_text" in query:
            query_text = query["query_text"]
            # Longer queries are more complex
            complexity_score += min(3, len(query_text.split()) / 10)
            
            # Multiple entity references increase complexity
            entity_count = len(query.get("entity_ids", []))
            complexity_score += min(3, entity_count * 0.5)
            
        # Determine complexity level
        if complexity_score < 5:
            return "low"
        elif complexity_score < 10:
            return "medium"
        else:
            return "high"
    


    def optimize_query(self, query: Dict[str, Any], priority: str = "normal", graph_processor: Any = None) -> Dict[str, Any]:
        """Plan a GraphRAG query.

        Returns a stable plan shape consumed by `get_execution_plan()` and the CLI.
        This implementation is intentionally conservative and must never raise on
        normal inputs.
        """
        if not isinstance(query, dict):
            raise ValueError("query must be a dict")

        # Defensive copy to avoid mutating caller input.
        planned_query: Dict[str, Any] = copy.deepcopy(query)

        # Normalize traversal parameters into the nested `traversal` object.
        traversal = planned_query.setdefault("traversal", {})
        if isinstance(traversal, dict):
            if "edge_types" in planned_query and "edge_types" not in traversal:
                traversal["edge_types"] = planned_query.pop("edge_types")
            if "max_traversal_depth" in planned_query and "max_depth" not in traversal:
                traversal["max_depth"] = planned_query.pop("max_traversal_depth")

        # Determine graph type best-effort.
        try:
            graph_type = self.detect_graph_type(planned_query)
        except Exception:
            graph_type = "general"

        optimizer = self._specific_optimizers.get(graph_type, self.base_optimizer)

        # Default weights.
        weights: Dict[str, float] = {
            "vector": float(getattr(optimizer, "vector_weight", 0.7)),
            "graph": float(getattr(optimizer, "graph_weight", 0.3)),
        }

        # If vector query, allow base optimizer to tune basic params.
        if "query_vector" in planned_query:
            try:
                vector_params = planned_query.get("vector_params", {})
                if not isinstance(vector_params, dict):
                    vector_params = {}

                max_vector_results = planned_query.get("max_vector_results", vector_params.get("top_k", 5))
                min_similarity = planned_query.get(
                    "min_similarity",
                    vector_params.get("min_score", vector_params.get("min_similarity", 0.5)),
                )

                optimized = optimizer.optimize_query(
                    query_vector=np.array(planned_query["query_vector"]),
                    max_vector_results=int(max_vector_results or 5),
                    max_traversal_depth=int(planned_query.get("traversal", {}).get("max_depth", 2) or 2),
                    edge_types=planned_query.get("traversal", {}).get("edge_types"),
                    min_similarity=float(min_similarity or 0.5),
                )

                if isinstance(optimized, dict):
                    opt_params = optimized.get("params", {})
                    if isinstance(opt_params, dict):
                        if "max_vector_results" in opt_params:
                            planned_query["max_vector_results"] = opt_params["max_vector_results"]
                        if "min_similarity" in opt_params:
                            planned_query["min_similarity"] = opt_params["min_similarity"]
                        if "max_traversal_depth" in opt_params and isinstance(planned_query.get("traversal"), dict):
                            planned_query["traversal"]["max_depth"] = opt_params["max_traversal_depth"]
                        if "edge_types" in opt_params and isinstance(planned_query.get("traversal"), dict):
                            if opt_params["edge_types"] is not None:
                                planned_query["traversal"]["edge_types"] = opt_params["edge_types"]

                    opt_weights = optimized.get("weights")
                    if isinstance(opt_weights, dict):
                        if "vector" in opt_weights and "graph" in opt_weights:
                            weights = {
                                "vector": float(opt_weights.get("vector", weights["vector"])),
                                "graph": float(opt_weights.get("graph", weights["graph"])),
                            }
            except Exception:
                pass

        # Allocate budget with safe fallback.
        try:
            budget = self.budget_manager.allocate_budget(planned_query, priority)
        except Exception:
            budget = {}

        if not isinstance(budget, dict):
            budget = {}

        budget.setdefault("vector_search_ms", 500)
        budget.setdefault("graph_traversal_ms", 1000)
        budget.setdefault("ranking_ms", 100)
        budget.setdefault("max_nodes", 100)

        # Cache metadata.
        caching: Dict[str, Any] = {"enabled": bool(getattr(optimizer, "cache_enabled", False))}
        if caching["enabled"]:
            try:
                key_query = copy.deepcopy(planned_query)
                if "query_vector" in key_query:
                    key_query["query_vector"] = "[vector]"
                caching["key"] = hashlib.sha256(
                    json.dumps(key_query, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
            except Exception:
                pass

        statistics = {
            "avg_query_time": getattr(getattr(self, "query_stats", None), "avg_query_time", 0.0),
            "cache_hit_rate": getattr(getattr(self, "query_stats", None), "cache_hit_rate", 0.0),
        }

        traversal_strategy = "default"
        if isinstance(planned_query.get("traversal"), dict):
            traversal_strategy = planned_query["traversal"].get("strategy", "default")

        return {
            "query": planned_query,
            "weights": weights,
            "budget": budget,
            "graph_type": graph_type,
            "statistics": statistics,
            "caching": caching,
            "traversal_strategy": traversal_strategy,
        }

    def _apply_learning_hook(self) -> None:
        """Best-effort: learn from recent query stats and adjust defaults."""
        apply_learning_hook(self)

    def get_execution_plan(self, query: Dict[str, Any], priority: str = "normal", graph_processor: Any = None) -> Dict[str, Any]:
        """
        Generate a detailed execution plan without executing the query.
    
        Args:
            query (Dict): Query to plan
            priority (str): Query priority
            graph_processor (Any, optional): GraphRAG processor for advanced optimizations
        
        Returns:
            Dict: Detailed execution plan
        """
        # Optimize query
        plan = self.optimize_query(query, priority, graph_processor)
    
        # Determine graph type
        graph_type = plan["graph_type"]
    
        # Create execution steps
        execution_steps = []
    
        if "query_vector" in query:
            # Get vector search parameters
            vector_params = {}
            if "vector_params" in plan["query"]:
                vector_params = plan["query"]["vector_params"]
        
            top_k = vector_params.get("top_k", plan["query"].get("max_vector_results", 5))
            min_score = vector_params.get("min_score", plan["query"].get("min_similarity", 0.5))
        
            # Get traversal parameters
            traversal_params = {}
            if "traversal" in plan["query"]:
                traversal_params = plan["query"]["traversal"]
            
            max_depth = traversal_params.get("max_depth", plan["query"].get("max_traversal_depth", 2))
            edge_types = traversal_params.get("edge_types", plan["query"].get("edge_types", []))
        
            # Create vector search step with additional parameters
            vector_step = {
                "name": "vector_similarity_search",
                "description": "Find initial matches by vector similarity",
                "budget_ms": plan["budget"]["vector_search_ms"],
                "params": {
                    "query_vector": "[vector data]",  # Placeholder
                    "top_k": top_k,
                    "min_score": min_score
                }
            }
        
            # Add special vector parameters if present
            for param_name, param_value in vector_params.items():
                if param_name not in ["top_k", "min_score"]:
                    vector_step["params"][param_name] = param_value
        
            # Determine traversal strategy description
            traversal_strategy = traversal_params.get("strategy", "default")
            if traversal_strategy == "entity_importance":
                traversal_description = "Entity importance-based graph traversal"
            elif traversal_strategy == "bidirectional":
                traversal_description = "Bidirectional search for fact verification"
            elif traversal_strategy == "dag_traversal":
                traversal_description = "DAG-optimized traversal for IPLD graphs"
            else:
                traversal_description = "Standard graph traversal"
        
            # Create graph traversal step with optimized parameters
            graph_step = {
                "name": "graph_traversal",
                "description": traversal_description,
                "budget_ms": plan["budget"]["graph_traversal_ms"],
                "params": {
                    "max_depth": max_depth,
                    "edge_types": edge_types,
                    "max_nodes": plan["budget"]["max_nodes"],
                    "strategy": traversal_strategy
                }
            }
        
            # Add additional traversal parameters
            for param_name, param_value in traversal_params.items():
                if param_name not in ["max_depth", "edge_types", "strategy"]:
                    # Don't include large entity score maps in execution plan
                    if param_name == "entity_scores" and isinstance(param_value, dict) and len(param_value) > 5:
                        graph_step["params"]["entity_scores"] = f"[{len(param_value)} entity scores]"
                    else:
                        graph_step["params"][param_name] = param_value
        
            # Create ranking step
            ranking_step = {
                "name": "result_ranking",
                "description": "Rank combined results",
                "budget_ms": plan["budget"]["ranking_ms"],
                "params": {
                    "vector_weight": plan["weights"].get("vector", 0.7),
                    "graph_weight": plan["weights"].get("graph", 0.3)
                }
            }
        
            execution_steps = [vector_step, graph_step, ranking_step]
        else:
            # Direct graph query with optimized traversal
            traversal_params = {}
            if "traversal" in plan["query"]:
                traversal_params = plan["query"]["traversal"]
            
            traversal_strategy = traversal_params.get("strategy", "default")
        
            # Create direct graph query step with strategy
            direct_query_step = {
                "name": "direct_graph_query",
                "description": f"Execute direct graph query with {traversal_strategy} strategy",
                "budget_ms": plan["budget"]["graph_traversal_ms"],
                "params": {
                    "strategy": traversal_strategy,
                    **{k: v for k, v in plan["query"].items() if k != "traversal"}
                }
            }
        
            # Add additional traversal parameters
            if traversal_params:
                direct_query_step["params"]["traversal_params"] = {
                    k: v for k, v in traversal_params.items() 
                    if k != "entity_scores" or (isinstance(v, dict) and len(v) <= 5)
                }
            
                # Summarize entity scores if present and large
                if "entity_scores" in traversal_params and isinstance(traversal_params["entity_scores"], dict) and len(traversal_params["entity_scores"]) > 5:
                    direct_query_step["params"]["traversal_params"]["entity_scores"] = f"[{len(traversal_params['entity_scores'])} entity scores]"
        
            execution_steps = [direct_query_step]
        
        # Add caching information
        caching_info = plan["caching"].copy()
        if "key" in caching_info:
            caching_info["key"] = caching_info["key"][:10] + "..."  # Truncate for readability
    
        # Add strategy performance if available
        strategy_performance = {}
        for strategy, stats in self._strategy_performance.items():
            if stats["count"] > 0:
                strategy_performance[strategy] = {
                    "avg_time": stats["avg_time"],
                    "relevance_score": stats["relevance_score"],
                    "count": stats["count"]
                }
    
        # Return detailed plan
        return {
            "graph_type": graph_type,
            "optimization_applied": True,
            "execution_steps": execution_steps,
            "caching": caching_info,
            "budget": plan["budget"],
            "statistics": plan["statistics"],
            "estimated_time_ms": sum(step["budget_ms"] for step in execution_steps),
            "priority": priority,
            "traversal_strategy": plan.get("traversal_strategy", "default"),
            "strategy_performance": strategy_performance if strategy_performance else None
        }
    
    def update_relation_usefulness(self, relation_type: str, query_success: float) -> None:
        """
        Update the usefulness score for a relation type based on query success.
    
        This method tracks which relation types contribute to successful queries
        and helps prioritize the most useful relations in future traversals.
    
        Args:
            relation_type: The type of relation to update
            query_success: Success score (0.0-1.0) for this relation in a query
        """
        if not relation_type:
            return
        
        # Get current usefulness or default
        current_usefulness = self._traversal_stats["relation_usefulness"].get(relation_type, 0.5)
    
        # Update with rolling average (80% old, 20% new)
        updated_usefulness = current_usefulness * 0.8 + query_success * 0.2
    
        # Store updated value
        self._traversal_stats["relation_usefulness"][relation_type] = updated_usefulness
    
    def enable_statistical_learning(self, enabled: bool = True, learning_cycle: int = 50) -> None:
        """
        Enable or disable statistical learning from past query performance.
    
        When enabled, the optimizer automatically analyzes past query performance
        and adjusts optimization parameters to improve future query results.
    
        Args:
            enabled: Whether to enable statistical learning
            learning_cycle: Number of recent queries to analyze for learning
        """
        self._learning_enabled = enabled
        self._learning_cycle = learning_cycle
    
        # Initialize entity importance cache if not exists
        if not hasattr(self, '_entity_importance_cache'):
            self._entity_importance_cache = {}
            
    def _check_learning_cycle(self):
        """
        Check if it's time to trigger a statistical learning cycle.
    
        This method should be called at the beginning of optimize_query to 
        determine if enough queries have been processed since the last
        learning cycle to trigger a new learning cycle.
    
        The method ensures robust error handling around the learning process,
        preventing any learning-related errors from affecting query optimization.
    
        Implements a circuit breaker pattern to disable learning after repeated failures.
        """
        check_learning_cycle(self)
    
    def _increment_failure_counter(self, error_message, is_critical=True):
        """
        Increment the learning failure counter and trip the circuit breaker if needed.
    
        Args:
        error_message: The error message to log
        is_critical: Whether the error is critical (counts more heavily)
        """
        increment_failure_counter(self, error_message, is_critical=is_critical)

    def save_learning_state(self, filepath=None) -> None:
        """
        Save the current learning state to disk.
    
        Args:
            filepath (str, optional): Path to save the state file. If None, uses default location.
        
        Returns:
            str: Path where the state was saved, or None if not saved
        """
        if not hasattr(self, '_learning_enabled') or not self._learning_enabled:
            return None
        
        # Use default path if none provided
        if filepath is None:
            if hasattr(self, 'metrics_dir') and self.metrics_dir:
                filepath = os.path.join(self.metrics_dir, "learning_state.json")
            else:
                # No valid filepath, can't save
                return None
            
        # Create state object
        state = {
            "learning_enabled": self._learning_enabled,
            "learning_cycle": self._learning_cycle,
            "learning_parameters": getattr(self, "_learning_parameters", {}),
            "traversal_stats": getattr(self, "_traversal_stats", {}),
            "entity_importance_cache": getattr(self, "_entity_importance_cache", {}),
            "timestamp": datetime.datetime.now().isoformat()
        }
    
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    
        try:
            # First apply numpy handling
            serializable_state = self._numpy_json_serializable(state)
        
            # Save state to file
            with open(filepath, 'w') as f:
                json.dump(serializable_state, f, indent=2)
            
            return filepath
        except Exception as e:
            # Handle serialization errors gracefully
            error_message = f"Error serializing learning state to JSON: {str(e)}"
        
            # Create a simplified version with just error information
            fallback_state = {
                "error": error_message,
                "timestamp": datetime.datetime.now().isoformat(),
                "partial_state": True,
                # Include some minimal state information
                "learning_enabled": state.get("learning_enabled", False),
                "learning_cycles_completed": state.get("learning_cycles_completed", 0)
            }
        
            # Try to save the fallback state
            try:
                with open(filepath, 'w') as f:
                    json.dump(fallback_state, f, indent=2)
                return filepath
            except:
                # If that also fails, log error and return None
                if hasattr(self, "metrics_collector") and self.metrics_collector is not None:
                    self.metrics_collector.record_additional_metric(
                        name="serialization_error",
                        value=f"Failed to save learning state: {error_message}",
                        category="error"
                    )
                return None
        
    def load_learning_state(self, filepath=None) -> None:
        """
        Load learning state from disk.
    
        Args:
            filepath (str, optional): Path to the state file. If None, uses default location.
        
        Returns:
            bool: True if state was loaded successfully, False otherwise
        """
        # Use default path if none provided
        if filepath is None:
            if hasattr(self, 'metrics_dir') and self.metrics_dir:
                filepath = os.path.join(self.metrics_dir, "learning_state.json")
            else:
                # No valid filepath, can't load
                return False
            
        # Check if file exists
        if not os.path.exists(filepath):
            return False
        
        try:
            # Load state from file
            with open(filepath, 'r') as f:
                state = json.load(f)
            
            # Set learning parameters
            self._learning_enabled = state.get("learning_enabled", False)
            self._learning_cycle = state.get("learning_cycle", 10)
        
            # Set learning parameters if present
            if "learning_parameters" in state:
                self._learning_parameters = state["learning_parameters"]
            
            # Set traversal stats if present
            if "traversal_stats" in state:
                self._traversal_stats = state["traversal_stats"]
            
            # Set entity importance cache if present
            if "entity_importance_cache" in state:
                self._entity_importance_cache = state["entity_importance_cache"]
            
            return True
        
        except Exception as e:
            # Handle load errors
            if hasattr(self, 'logger'):
                self.logger.error(f"Error loading learning state: {str(e)}")
            return False
        
        # Initialize default parameters if not exists
        if not hasattr(self, '_default_max_depth'):
            self._default_max_depth = 2
        if not hasattr(self, '_default_vector_top_k'):
            self._default_vector_top_k = 5
        if not hasattr(self, '_default_min_similarity'):
            self._default_min_similarity = 0.7
        if not hasattr(self, '_default_traversal_strategy'):
            self._default_traversal_strategy = "breadth_first"
        
        # Log status of statistical learning
        print(f"Statistical learning for query optimization: {'enabled' if enabled else 'disabled'}")
        if enabled:
            print(f"Learning from {learning_cycle} most recent queries")
    
    def record_path_performance(self, 
                                path: List[str], 
                                success_score: float, 
                                relation_types: List[str] = None) -> None:
        """
        Record the performance of a specific traversal path.
    
        This helps track which paths through the graph are most successful
        and can inform future traversal strategy choices.
    
        Args:
            path: List of node IDs in the path
            success_score: How successful this path was (0.0-1.0)
            relation_types: Optional list of relation types in this path
        """
        if not path or len(path) < 2:
            return
        
        # Create a path key (using just first and last nodes to keep keys manageable)
        path_key = f"{path[0]}...{path[-1]}({len(path)})"
    
        # Record this path
        self._traversal_stats["paths_explored"].append(path_key)
    
        # Record path score
        current_score = self._traversal_stats["path_scores"].get(path_key, 0.0)
        # Update with rolling average (70% old, 30% new)
        self._traversal_stats["path_scores"][path_key] = current_score * 0.7 + success_score * 0.3
    
        # Update relation type usefulness if provided
        if relation_types:
            for relation_type in relation_types:
                self.update_relation_usefulness(relation_type, success_score)
            
        # Record entity frequency
        for entity_id in path:
            self._traversal_stats["entity_frequency"][entity_id] += 1
    
    def execute_query_with_caching(
        self,
        query_func: Callable[[Any, Dict[str, Any]], Any],
        query_vector: Any,
        params: Dict[str, Any],
        graph_processor: Any = None
    ) -> Any:
        """
        Execute a query with caching and performance tracking.
        
        Args:
            query_func (Callable): Function that executes the query
            query_vector (np.ndarray): Query vector
            params (Dict): Query parameters
            graph_processor (Any, optional): GraphRAG processor for advanced optimizations
            
        Returns:
            Any: Query results
        """
        # Create query representation
        query = {
            "query_vector": query_vector,
            **params
        }
        
        # Generate optimized plan with graph processor for advanced optimizations
        plan = self.optimize_query(query, "normal", graph_processor)
        
        # Check cache
        if "key" in plan["caching"] and plan["caching"]["enabled"]:
            cache_key = plan["caching"]["key"]
            optimizer = self._specific_optimizers.get(plan["graph_type"], self.base_optimizer)
            if optimizer.is_in_cache(cache_key):
                cached_results = optimizer.get_from_cache(cache_key)
                
                # Track query statistics for cache hits
                if hasattr(self, "query_stats") and self.query_stats is not None:
                    # Record cache hit (don't increment query_count for cache hits)
                    self.query_stats.record_cache_hit()
                    
                    # Do NOT call record_query_time for cache hits to avoid incrementing query_count
                    # Instead, update other statistics directly
                    self.query_stats.total_query_time += 0.001  # Minimal time for cached results
                    self.query_stats.query_times.append(0.001)
                    self.query_stats.query_timestamps.append(time.time())
                
                # Even for cached results, track some minimal statistics
                if hasattr(cached_results, "__len__") and len(cached_results) > 0:
                    # For successful cached queries, update importance of caching
                    avg_score = 0.0
                    if hasattr(cached_results[0], "get") and "score" in cached_results[0]:
                        avg_score = sum(r.get("score", 0) for r in cached_results[:3]) / min(3, len(cached_results))
                        
                    # Record minimal statistics for cached results
                    if "traversal" in params and "edge_types" in params["traversal"]:
                        for edge_type in params["traversal"]["edge_types"]:
                            self.update_relation_usefulness(edge_type, avg_score)
                
                return cached_results
        
        # Execute query
        start_time = time.time()
        results = query_func(query_vector, params)
        execution_time = time.time() - start_time
        
        # Track statistics
        self.query_stats.record_query_time(execution_time)
        
        # Track performance of paths if results include path information
        if hasattr(results, "__len__") and len(results) > 0:
            # Extract path information if present in results
            for i, result in enumerate(results[:5]):  # Look at top 5 results
                if hasattr(result, "get"):
                    # Calculate a success score based on position and score
                    position_weight = 1.0 - (i * 0.15)  # Position 0 = 1.0, position 1 = 0.85, etc.
                    score = result.get("score", 0.5)
                    success_score = position_weight * score
                    
                    # Extract path if present
                    path = result.get("path")
                    relation_types = result.get("relation_types")
                    
                    if path:
                        self.record_path_performance(path, success_score, relation_types)
        
        # Cache results
        if "key" in plan["caching"] and plan["caching"]["enabled"]:
            optimizer = self._specific_optimizers.get(plan["graph_type"], self.base_optimizer)
            optimizer.add_to_cache(plan["caching"]["key"], results)
            
        return results


    def visualize_query_plan(self, query_id=None, output_file=None, show_plot=True, figsize=(12, 8)):
        """
        Visualize the execution plan of a query.
        
        Args:
            query_id (str, optional): Query ID to visualize, most recent if None
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            figsize (tuple): Figure size in inches
            
        Returns:
            Figure or None: The matplotlib figure if available
        """
        if not VISUALIZATION_AVAILABLE:
            print("Visualization dependencies not available. Install matplotlib and networkx.")
            return None
            
        if not hasattr(self, "metrics_collector") or not self.metrics_collector:
            print("No metrics collector available. Cannot visualize query plan.")
            return None
            
        # Get the query metrics
        if query_id is None:
            # Use last query if available
            if hasattr(self, "last_query_id") and self.last_query_id:
                query_id = self.last_query_id
            else:
                # Get most recent query
                recent = self.metrics_collector.get_recent_metrics(1)
                if not recent:
                    print("No recent queries to visualize.")
                    return None
                query_id = recent[0]["query_id"]
        
        metrics = self.metrics_collector.get_query_metrics(query_id)
        if not metrics:
            print(f"No metrics found for query ID: {query_id}")
            return None
            
        # Create a query plan dictionary from the metrics
        plan = {
            "phases": metrics.get("phases", {}),
            "query_id": query_id,
            "execution_time": metrics.get("duration", 0),
            "params": metrics.get("params", {})
        }
        
        # Use the visualizer to display the plan
        if hasattr(self, "visualizer") and self.visualizer:
            return self.visualizer.visualize_query_plan(
                query_plan=plan,
                title=f"Query Plan for {query_id[:8]}",
                show_plot=show_plot,
                output_file=output_file,
                figsize=figsize
            )
        else:
            print("No visualizer available. Cannot create visualization.")
            return None
    
    def visualize_metrics_dashboard(self, query_id=None, output_file=None, include_all_metrics=False) -> None:
        """
        Generate a comprehensive metrics dashboard for visualization.
        
        Args:
            query_id (str, optional): Specific query ID to focus on
            output_file (str, optional): Path to save the dashboard
            include_all_metrics (bool): Whether to include all available metrics
            
        Returns:
            str or None: Path to the generated dashboard if successful
        """
        if not hasattr(self, "visualizer") or not self.visualizer:
            print("No visualizer available. Cannot create dashboard.")
            return None
            
        if not hasattr(self, "metrics_collector") or not self.metrics_collector:
            print("No metrics collector available. Cannot create dashboard.")
            return None
            
        # Set default output file if not provided
        if not output_file and hasattr(self.metrics_collector, "metrics_dir") and self.metrics_collector.metrics_dir:
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            output_file = os.path.join(self.metrics_collector.metrics_dir, f"dashboard_{timestamp}.html")
            
        # Generate dashboard
        self.visualizer.export_dashboard_html(
            output_file=output_file,
            query_id=query_id,
            include_all_metrics=include_all_metrics
        )
        
        return output_file
    
    def visualize_performance_comparison(self, query_ids=None, labels=None, output_file=None, show_plot=True) -> None:
        """
        Compare performance metrics across multiple queries.
        
        Args:
            query_ids (List[str], optional): List of query IDs to compare
            labels (List[str], optional): Labels for each query
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            
        Returns:
            Figure or None: The matplotlib figure if available
        """
        if not hasattr(self, "visualizer") or not self.visualizer:
            print("No visualizer available. Cannot create visualization.")
            return None
            
        if not hasattr(self, "metrics_collector") or not self.metrics_collector:
            print("No metrics collector available. Cannot create visualization.")
            return None
            
        # If no query IDs provided, use most recent queries
        if not query_ids:
            recent_metrics = self.metrics_collector.get_recent_metrics(count=5)
            query_ids = [m["query_id"] for m in recent_metrics]
            
        # Generate comparison visualization
        return self.visualizer.visualize_performance_comparison(
            query_ids=query_ids,
            labels=labels,
            show_plot=show_plot,
            output_file=output_file
        )
    
    def visualize_resource_usage(self, query_id=None, output_file=None, show_plot=True) -> None:
        """
        Visualize resource usage (memory and CPU) for a specific query.
        
        Args:
            query_id (str, optional): Query ID to visualize, most recent if None
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            
        Returns:
            Figure or None: The matplotlib figure if available
        """
        if not hasattr(self, "visualizer") or not self.visualizer:
            print("No visualizer available. Cannot create visualization.")
            return None
            
        if not hasattr(self, "metrics_collector") or not self.metrics_collector:
            print("No metrics collector available. Cannot create visualization.")
            return None
            
        # If no query ID provided, use the most recent query
        if not query_id:
            if hasattr(self, "last_query_id") and self.last_query_id:
                query_id = self.last_query_id
            else:
                recent = self.metrics_collector.get_recent_metrics(1)
                if not recent:
                    print("No recent queries to visualize.")
                    return None
                query_id = recent[0]["query_id"]
                
        # Generate resource usage visualization
        return self.visualizer.visualize_resource_usage(
            query_id=query_id,
            show_plot=show_plot,
            output_file=output_file
        )
    
    def visualize_query_patterns(self, limit=10, output_file=None, show_plot=True) -> None:
        """
        Visualize common query patterns from collected metrics.
        
        Args:
            limit (int): Maximum number of patterns to display
            output_file (str, optional): Path to save the visualization
            show_plot (bool): Whether to display the plot
            
        Returns:
            Figure or None: The matplotlib figure if available
        """
        if not hasattr(self, "visualizer") or not self.visualizer:
            print("No visualizer available. Cannot create visualization.")
            return None
            
        # Generate query patterns visualization
        return self.visualizer.visualize_query_patterns(
            limit=limit,
            show_plot=show_plot,
            output_file=output_file
        )

    def export_metrics_to_csv(self, filepath=None) -> None:
        """
        Export collected metrics to CSV format.
        
        Args:
            filepath (str, optional): Path to save the CSV file
            
        Returns:
            str or None: CSV content as string if filepath is None, otherwise None
        """
        if not hasattr(self, "metrics_collector") or not self.metrics_collector:
            print("No metrics collector available. Cannot export metrics.")
            return None
            
        return self.metrics_collector.export_metrics_csv(filepath)
