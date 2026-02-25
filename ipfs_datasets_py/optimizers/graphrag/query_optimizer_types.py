"""Typed return contracts for GraphRAG query optimizer API.

Provides typed definitions for all public method return values,
replacing ambiguous `Dict[str, Any]` with structured TypedDict classes
and type aliases.
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


class ValidatedQueryParameters(TypedDict, total=False):
    """Query parameters after validation and normalization."""
    query_text: str
    max_vector_results: int
    min_similarity: float
    traversal: Dict[str, Any]
    priority: str
    graph_type: str
    entity_ids: List[str]
    metadata: Dict[str, Any]


class FallbackQueryPlan(TypedDict, total=False):
    """Fallback query plan when optimization fails."""
    query: Dict[str, Any]
    weights: Dict[str, float]
    budget: Dict[str, Any]
    graph_type: str
    statistics: Dict[str, Any]
    caching: Dict[str, Any]
    traversal_strategy: str
    fallback: bool
    error: Optional[str]


class EnhancedTraversalParameters(TypedDict, total=False):
    """Traversal parameters enhanced for specific query types."""
    strategy: str
    max_depth: int
    bidirectional_entity_limit: int
    path_ranking: str
    wikidata_fact_verification: bool
    validation_threshold: float
    fact_verification: Dict[str, Any]
    source_entity: str
    target_entity: str
    relation_detection: bool
    expected_relationship: str
    relationship_priority: str
    citation_analysis: Dict[str, Any]


class ExtractionStatistics(TypedDict, total=False):
    """Comprehensive extraction statistics and metrics."""
    total_entities: int
    total_relationships: int
    unique_types: int
    entities_with_properties: int
    avg_confidence: float
    min_confidence: float
    max_confidence: float
    entities_by_type: Dict[str, int]
    relationship_types: List[str]
    dangling_relationships: int
    avg_text_length: float


class RelationshipCoherenceIssues(TypedDict, total=False):
    """Analysis of relationship quality and coherence issues."""
    low_confidence_relationships: List[tuple]
    dangling_relationships: List[tuple]
    self_relationships: List[tuple]
    duplicate_relationships: List[List[str]]
    high_degree_entities: List[tuple]
    total_issues: int


class SyntheticOntologyResult(TypedDict, total=False):
    """Result from synthetic ontology generation."""
    entities: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    domain: str


class EntityDictSerialization(TypedDict, total=False):
    """Serialized entity representation."""
    id: str
    type: str
    text: str
    confidence: float
    properties: Dict[str, Any]
    source_span: Optional[List[int]]
    last_seen: Optional[float]


class RelationshipDictSerialization(TypedDict, total=False):
    """Serialized relationship representation."""
    id: str
    source_id: str
    target_id: str
    type: str
    properties: Dict[str, Any]
    confidence: float
    direction: str


# TIER 3: Metrics and Analysis Contracts
# These use type aliases instead of TypedDict since they're flexible key-value mappings

# Type alias: confidence histogram mapping bucket labels to entity counts
# Example: {"0.0-0.2": 5, "0.2-0.4": 3, ...}
ConfidenceHistogram = Dict[str, int]

# Type alias: entity type distribution mapping type names to relative frequencies
# Example: {"Person": 0.5, "Organization": 0.3, "Date": 0.2}
EntityTypeDistribution = Dict[str, float]

# Type alias: entity counts grouped by type
# Example: {"Person": 5, "Organization": 3, "Date": 2}
EntityCountByType = Dict[str, int]

# Type alias: relationship type counts
# Example: {"works_for": 10, "knows": 8, "located_in": 5}
RelationshipTypeCounts = Dict[str, int]


# TIER 4: Advanced Analysis and Summary Contracts
ConfidenceQuartiles = TypedDict(
    "ConfidenceQuartiles",
    {"q1": float, "q2": float, "q3": float},
    total=False
)
# Example: {"q1": 0.45, "q2": 0.72, "q3": 0.88}
# Maps quartile names (25th, 50th, 75th percentile) to confidence scores

RelationshipDensityByType = Dict[str, float]
# Example: {"works_for": 0.35, "knows": 0.25, "located_in": 0.40}
# Maps relationship types to their fraction of total relationships

EntityIDPrefixGroups = Dict[str, list]
# Example: {"a": ["alice", "alex"], "b": ["bob", "bert"], "c": ["charlie"]}
# Groups entity IDs by their first N characters (prefix_len parameter)

RelationshipSourceDegreeDistribution = Dict[str, int]
# Example: {"e1": 3, "e2": 1, "e3": 2}
# Maps each source entity ID to how many relationships it originates from (out-degree)

ResultSummaryDict = TypedDict(
    "ResultSummaryDict",
    {
        "entity_count": int,
        "relationship_count": int,
        "unique_types": int,
        "mean_confidence": float,
        "min_confidence": float,
        "max_confidence": float,
        "has_errors": bool,
        "error_count": int,
    },
    total=False
)
# Example: {"entity_count": 42, "relationship_count": 68, "unique_types": 5, ...}
# Structured summary of extraction result metrics


# TIER 5: Validator and Quality Assessment Contracts

MergeEvidenceDict = TypedDict(
    "MergeEvidenceDict",
    {
        "name_similarity": float,
        "type_match": bool,
        "type1": str,
        "type2": str,
        "confidence1": float,
        "confidence2": float,
        "confidence_difference": float,
    },
    total=False
)
# Example: {"name_similarity": 0.85, "type_match": True, "type1": "Organization", ...}
# Evidence dictionary for entity merge suggestions

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
    "ValidatedQueryParameters",
    "FallbackQueryPlan",
    "EnhancedTraversalParameters",
    "ExtractionStatistics",
    "RelationshipCoherenceIssues",
    "SyntheticOntologyResult",
    "EntityDictSerialization",
    "RelationshipDictSerialization",
    # TIER 3 metrics and analysis contracts
    "ConfidenceHistogram",
    "EntityTypeDistribution",
    "EntityCountByType",
    "RelationshipTypeCounts",
    # TIER 4 advanced analysis and summary contracts
    "ConfidenceQuartiles",
    "RelationshipDensityByType",
    "EntityIDPrefixGroups",
    "RelationshipSourceDegreeDistribution",
    "ResultSummaryDict",
    "MergeEvidenceDict",
    "MergeEvidenceDict",
]
