"""Typed return contracts for GraphRAG query optimizer API.

Provides typed definitions for all public method return values,
replacing ambiguous `Dict[str, Any]` with structured TypedDict classes.
"""

from typing import Any, Dict, List, Optional, TypedDict


class QueryOptimizationPlanStep(TypedDict, total=False):
    """Single step in a query execution plan."""
    step_type: str  # e.g., "vector_search", "graph_traversal", "ranking"
    description: str
    estimated_time_ms: float
    resource_estimate: Dict[str, Any]


class QueryOptimizationPlan(TypedDict, total=False):
    """Complete execution plan for a query optimization."""
    query: Dict[str, Any]
    weights: Dict[str, float]
    budget: Dict[str, Any]
    graph_type: str  # "wikipedia", "ipld", or "mixed"
    statistics: Dict[str, float]
    steps: List[QueryOptimizationPlanStep]
    caching: Dict[str, Any]
    traversal_strategy: str
    estimated_total_time_ms: float


class TraversalOptimization(TypedDict, total=False):
    """Result of optimized query traversal."""
    query: Dict[str, Any]
    edge_types: List[str]
    traversal_costs: Dict[str, float]
    entity_importance: Dict[str, float]
    relationship_weights: Dict[str, float]


class QueryOptimizationResult(TypedDict, total=False):
    """Complete result from query optimization."""
    query: Dict[str, Any]
    weights: Dict[str, float]
    budget: Dict[str, Any]
    graph_type: str
    statistics: Dict[str, float]
    caching: Dict[str, Any]
    traversal_strategy: str
    execution_metrics: Dict[str, Any]


class PerformanceAnalysis(TypedDict, total=False):
    """Analysis of query optimizer performance."""
    avg_query_time_ms: float
    total_queries: int
    cache_hit_rate: float
    optimization_suggestions: List[str]
    bottlenecks: List[str]
    recommendations: List[Dict[str, Any]]


class BudgetAllocation(TypedDict, total=False):
    """Allocated resource budget for a query."""
    vector_search_ms: float
    graph_traversal_ms: float
    ranking_ms: float
    max_nodes: int
    max_edges: int
    cache_budget_kb: float


class ConsumptionReport(TypedDict, total=False):
    """Current resource consumption report."""
    vector_search_time_ms: float
    graph_traversal_time_ms: float
    ranking_time_ms: float
    nodes_visited: int
    edges_traversed: int
    cache_entries_used: int
    total_time_ms: float


class WikipediaTraversalOptimization(TypedDict, total=False):
    """Traversal optimization specific to Wikipedia graphs."""
    query: Dict[str, Any]
    edge_priority: List[str]
    traversal_costs: Dict[str, float]
    entity_scores: Dict[str, float]
    relationship_activation_depths: Dict[str, int]


class IPLDTraversalOptimization(TypedDict, total=False):
    """Traversal optimization specific to IPLD graphs."""
    query: Dict[str, Any]
    cid_paths: List[str]
    traversal_strategy: str
    cache_strategy: str
    dag_exploration_depth: int


__all__ = [
    "QueryOptimizationPlanStep",
    "QueryOptimizationPlan",
    "TraversalOptimization",
    "QueryOptimizationResult",
    "PerformanceAnalysis",
    "BudgetAllocation",
    "ConsumptionReport",
    "WikipediaTraversalOptimization",
    "IPLDTraversalOptimization",
]
