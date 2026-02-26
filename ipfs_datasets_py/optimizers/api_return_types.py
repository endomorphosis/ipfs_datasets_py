"""Batch 328: API Return Type Consistency Implementation

Provides typed dataclass definitions for common API return types.
Replaces Dict[str, Any] with self-documenting, type-safe alternatives.

Usage:
    from .api_return_types import ExtractorResult, CriticResult
    
    # Instead of: return {"entities": [...], "count": 5}
    # Use: return ExtractorResult(entities=[...], entity_count=5)

"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional, List, TypedDict
from enum import Enum


class OperationStatus(Enum):
    """Status of completed operations."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMEOUT = "timeout"


class SerializedResultDict(TypedDict, total=False):
    """TypedDict for serialized dataclass result representation.
    
    Fields:
        (dynamic): Any serialized fields from source dataclass
    """
    pass


class JsonSerializableDict(TypedDict, total=False):
    """TypedDict for JSON-serializable result representation.
    
    Fields:
        (dynamic): Serialized fields with primitive types (no Enum)
    """
    pass


@dataclass
class ExtractorResult:
    """Result from entity/relationship extraction operations.
    
    Attributes:
        entities: List of extracted entity names
        entity_count: Total number of entities found
        extraction_time_ms: Time taken for extraction in milliseconds
        confidence_scores: Confidence score for each entity [0.0, 1.0]
        relationships: Optional relationship pairs
        status: Overall operation status
    """
    entities: List[str]
    entity_count: int
    extraction_time_ms: float
    confidence_scores: List[float]
    relationships: List[tuple] = field(default_factory=list)
    status: OperationStatus = OperationStatus.SUCCESS
    
    def __bool__(self) -> bool:
        """Result is truthy if entities were found."""
        return self.entity_count > 0
    
    @property
    def mean_confidence(self) -> float:
        """Average confidence across all extracted entities."""
        if not self.confidence_scores:
            return 0.0
        return sum(self.confidence_scores) / len(self.confidence_scores)
    
    @property
    def min_confidence(self) -> float:
        """Minimum confidence score."""
        return min(self.confidence_scores) if self.confidence_scores else 0.0
    
    @property
    def max_confidence(self) -> float:
        """Maximum confidence score."""
        return max(self.confidence_scores) if self.confidence_scores else 0.0


@dataclass
class CriticResult:
    """Result from critic evaluation across dimensions.
    
    Attributes:
        dimension_name: Name of evaluated dimension
        score: Evaluation score [0, max_score]
        max_score: Maximum possible score
        issues: List of identified issues
        recommendations: Recommendations for improvement
        status: Evaluation status
    """
    dimension_name: str
    score: float
    max_score: float = 1.0
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    status: OperationStatus = OperationStatus.SUCCESS
    
    @property
    def normalized_score(self) -> float:
        """Score normalized to [0, 1] range."""
        if self.max_score == 0:
            return 0.0
        normalized = self.score / self.max_score
        return min(1.0, max(0.0, normalized))
    
    @property
    def is_passing(self) -> bool:
        """Whether dimension meets passing threshold (0.8)."""
        return self.normalized_score >= 0.8
    
    @property
    def has_issues(self) -> bool:
        """Whether there are identified issues."""
        return len(self.issues) > 0


@dataclass
class OntologyResult:
    """Result from ontology/graph operations.
    
    Attributes:
        entity_count: Total entities in graph
        relationship_count: Total relationships
        avg_connections: Average connections per entity
        max_connections: Maximum connections for any entity
        min_connections: Minimum connections
        confidence_mean: Mean confidence of all entities
        confidence_std: Standard deviation of confidence
    """
    entity_count: int
    relationship_count: int
    avg_connections: float
    max_connections: int
    min_connections: int = 0
    confidence_mean: float = 0.0
    confidence_std: float = 0.0
    
    @property
    def density(self) -> float:
        """Graph density: actual edges / possible edges."""
        if self.entity_count <= 1:
            return 0.0
        max_edges = self.entity_count * (self.entity_count - 1) / 2
        return self.relationship_count / max_edges if max_edges > 0 else 0.0
    
    @property
    def is_sparse(self) -> bool:
        """Whether graph is sparse (density < 0.1)."""
        return self.density < 0.1
    
    @property
    def is_dense(self) -> bool:
        """Whether graph is dense (density > 0.5)."""
        return self.density > 0.5


@dataclass
class ValidationResult:
    """Result from validation operations.
    
    Attributes:
        is_valid: Whether validation passed
        error_count: Number of validation errors
        warning_count: Number of warnings
        errors: List of validation errors
        warnings: List of validation warnings
        details: Additional context about validation
    """
    is_valid: bool
    error_count: int
    warning_count: int
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def total_issues(self) -> int:
        """Total issues (errors + warnings)."""
        return self.error_count + self.warning_count
    
    @property
    def has_errors(self) -> bool:
        """Whether there are errors."""
        return self.error_count > 0
    
    @property
    def has_warnings(self) -> bool:
        """Whether there are warnings."""
        return self.warning_count > 0


@dataclass
class QueryPlanResult:
    """Result from query planning operations.
    
    Attributes:
        nodes: Query plan nodes (execution steps)
        node_count: Number of plan nodes
        optimization_score: Optimization quality score [0, 1]
        estimated_cost: Estimated execution cost
        plan_id: Unique plan identifier
        traversal_strategy: Query traversal strategy (bfs, dfs, etc.)
    """
    nodes: List[Dict[str, Any]]
    node_count: int
    optimization_score: float
    estimated_cost: float
    plan_id: str = ""
    traversal_strategy: str = "bfs"
    
    @property
    def is_optimized(self) -> bool:
        """Whether plan meets optimization threshold (0.85)."""
        return self.optimization_score >= 0.85
    
    @property
    def is_efficient(self) -> bool:
        """Whether plan has low estimated cost."""
        # Threshold assumes typical costs are under 100
        return self.estimated_cost < 50.0


@dataclass
class BatchResult:
    """Result from batch processing operations.
    
    Attributes:
        successful_count: Number of successful items
        failed_count: Number of failed items
        total_count: Total items processed
        processing_time_ms: Total processing time
        items: Details about each processed item
        errors: Errors encountered during processing
    """
    successful_count: int
    failed_count: int
    total_count: int
    processing_time_ms: float
    items: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Percentage of successful items."""
        if self.total_count == 0:
            return 0.0
        return (self.successful_count / self.total_count) * 100.0
    
    @property
    def failure_rate(self) -> float:
        """Percentage of failed items."""
        if self.total_count == 0:
            return 0.0
        return (self.failed_count / self.total_count) * 100.0
    
    @property
    def avg_time_per_item(self) -> float:
        """Average processing time per item."""
        if self.total_count == 0:
            return 0.0
        return self.processing_time_ms / self.total_count


@dataclass
class RefinementResult:
    """Result from refinement/optimization operations.
    
    Attributes:
        original_score: Score before refinement
        refined_score: Score after refinement
        improvement_pct: Percentage improvement
        iterations: Number of refinement iterations
        converged: Whether optimization converged
        refine_details: Details about what was refined
    """
    original_score: float
    refined_score: float
    improvement_pct: float
    iterations: int
    converged: bool
    refine_details: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_improved(self) -> bool:
        """Whether refinement improved the score."""
        return self.refined_score > self.original_score
    
    @property
    def efficiency_ratio(self) -> float:
        """Improvement per iteration."""
        if self.iterations == 0:
            return 0.0
        return self.improvement_pct / self.iterations


@dataclass
class ComparisonResult:
    """Result from comparison operations.
    
    Attributes:
        item_a: First compared item
        item_b: Second compared item
        similarity_score: Similarity [0, 1]
        differences: List of differences
        recommendation: Which item is better (if any)
    """
    item_a: Dict[str, Any]
    item_b: Dict[str, Any]
    similarity_score: float
    differences: List[str] = field(default_factory=list)
    recommendation: Optional[str] = None
    
    @property
    def is_similar(self) -> bool:
        """Whether items are similar (score > 0.7)."""
        return self.similarity_score > 0.7
    
    @property
    def is_identical(self) -> bool:
        """Whether items are identical (score = 1.0)."""
        return self.similarity_score >= 0.99


def to_dict(result: Any) -> SerializedResultDict:
    """Convert any result dataclass to dict.
    
    Args:
        result: Result dataclass instance
        
    Returns:
        Dictionary representation of result
    """
    if hasattr(result, '__dataclass_fields__'):
        return asdict(result)
    return dict(result) if isinstance(result, dict) else {}


def to_json_serializable(result: Any) -> JsonSerializableDict:
    """Convert result to JSON-serializable dict.
    
    Args:
        result: Result dataclass instance
        
    Returns:
        JSON-serializable dictionary
    """
    result_dict = to_dict(result)
    
    # Convert Enum values to strings
    for key, value in result_dict.items():
        if isinstance(value, Enum):
            result_dict[key] = value.value
    
    return result_dict
