"""Typed return contracts for GraphRAG ontology optimizer API.

Provides typed definitions for all public method return values,
replacing ambiguous `Dict[str, Any]` with structured TypedDict classes.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ExtractionMetadata(TypedDict, total=False):
    """Metadata about an extraction round."""
    entities_found: int
    relationships_found: int
    extraction_time_ms: float
    confidence_avg: float
    extraction_method: str


class CriticFeedback(TypedDict, total=False):
    """Feedback from the critic on an ontology."""
    completeness: float
    consistency: float
    clarity: float
    granularity: float
    domain_alignment: float
    overall_score: float
    issues: List[str]
    suggestions: List[str]


class OptimizationRound(TypedDict, total=False):
    """Single cycle of the optimization loop."""
    iteration: int
    initial_score: float
    optimized_score: float
    score_improvement: float
    entities_modified: int
    relationships_modified: int
    execution_time_ms: float
    feedback: CriticFeedback
    actions_taken: List[str]


class OntologyOptimizationHistory(TypedDict, total=False):
    """Historical data from ontology optimization."""
    total_rounds: int
    initial_score: float
    final_score: float
    total_improvement: float
    best_score: float
    rounds_to_peak: int
    convergence_threshold_met: bool
    rounds: List[OptimizationRound]
    execution_time_ms: float


class ValidationResult(TypedDict, total=False):
    """Result of ontology validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    dangling_references: List[str]
    consistency_score: float
    completeness_score: float


class OntologyDiffSummary(TypedDict, total=False):
    """Summary of changes between two ontologies."""
    entities_added: int
    entities_removed: int
    entities_modified: int
    relationships_added: int
    relationships_removed: int
    relationships_modified: int
    score_delta: float
    similarity_before: float
    similarity_after: float


class RefinementRecommendation(TypedDict, total=False):
    """Recommendation for further refinement."""
    action: str  # e.g., "split_entity", "merge_entities", "add_relationships"
    target_entities: List[str]
    rationale: str
    estimated_score_improvement: float
    confidence: float
    priority: str  # "high", "medium", "low"


class MediatorState(TypedDict, total=False):
    """State of the ontology mediator."""
    current_ontology: Dict[str, Any]
    undo_stack_depth: int
    stash_stack_depth: int
    recommendation_history: List[str]
    actions_history: List[str]
    session_score: float


class LearningCycleResult(TypedDict, total=False):
    """Result of a learning adaptation cycle."""
    feedback_count: int
    feedback_records: List[Dict[str, Any]]
    updates_applied: int
    new_patterns_discovered: int
    confidence_threshold_adjustments: Dict[str, float]
    threshold_updated: bool
    suggested_next_action: Optional[str]


class EmbeddingDeduplicationResult(TypedDict, total=False):
    """Result of semantic deduplication."""
    original_entity_count: int
    deduplicated_entity_count: int
    merge_groups: List[List[str]]
    entities_merged: int
    similarity_threshold_used: float
    execution_time_ms: float


class PipelineMetrics(TypedDict, total=False):
    """Metrics for an ontology generation pipeline run."""
    phase: str
    total_input_tokens: int
    entity_extraction_time_ms: float
    relationship_inference_time_ms: float
    consistency_check_time_ms: float
    total_time_ms: float
    entities_generated: int
    relationships_generated: int
    quality_score: float
    memory_peak_mb: float


__all__ = [
    "ExtractionMetadata",
    "CriticFeedback",
    "OptimizationRound",
    "OntologyOptimizationHistory",
    "ValidationResult",
    "OntologyDiffSummary",
    "RefinementRecommendation",
    "MediatorState",
    "LearningCycleResult",
    "EmbeddingDeduplicationResult",
    "PipelineMetrics",
]
