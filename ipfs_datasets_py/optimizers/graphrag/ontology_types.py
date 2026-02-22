"""Type definitions for GraphRAG ontology optimization module.

This module provides comprehensive TypedDict definitions for data structures
used throughout the GraphRAG optimizer components, enabling static type checking
and improved IDE support.

Key type categories:
- **Ontology Structures**: Entity, Relationship, Ontology, OntologyMetadata
- **Extraction Results**: EntityExtractionResult, RelationshipExtractionResult
- **Evaluation/Critique**: CriticScore, DimensionalScore, CriticRecommendation
- **Sessions & Context**: OntologySession, GenerationContext, RefineamentCycle
- **Statistics & Metrics**: StatisticalMetrics, PerformanceMetrics, QualityMetrics
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    TypedDict,
    Union,
    Literal,
    NotRequired,
)


# ============================================================================
# Ontology Structure Types
# ============================================================================


class Entity(TypedDict):
    """Represents an extracted entity in the ontology.
    
    Attributes:
        id: Unique identifier for the entity
        text: Original text of the entity
        type: Entity type/category (e.g., "Person", "Organization")
        confidence: Confidence score (0-1) of extraction
        properties: Optional key-value properties of the entity
        context: Optional context where entity was found
        source_span: Optional (start, end) character offsets in source text
    """
    id: str
    text: str
    type: str
    confidence: float
    properties: NotRequired[Dict[str, Any]]
    context: NotRequired[str]
    source_span: NotRequired[Tuple[int, int]]


class Relationship(TypedDict):
    """Represents an inferred relationship between entities.
    
    Attributes:
        id: Unique identifier for the relationship
        source_id: ID of source entity
        target_id: ID of target entity
        type: Relationship type/predicate (e.g., "works_at", "located_in")
        confidence: Confidence score (0-1) of inference
        properties: Optional key-value properties of the relationship
        context: Optional context where relationship was inferred
        distance: Optional co-occurrence distance that influenced inference
    """
    id: str
    source_id: str
    target_id: str
    type: str
    confidence: float
    properties: NotRequired[Dict[str, Any]]
    context: NotRequired[str]
    distance: NotRequired[int]


class OntologyMetadata(TypedDict):
    """Metadata about an ontology generation.
    
    Attributes:
        source: Source data identifier
        domain: Domain of the ontology (e.g., "legal", "medical")
        strategy: Extraction strategy used
        timestamp: ISO timestamp of generation
        version: Version identifier
        config: Extraction configuration used
    """
    source: str
    domain: str
    strategy: str
    timestamp: str
    version: str
    config: NotRequired[Dict[str, Any]]


class Ontology(TypedDict):
    """Complete ontology representation.
    
    Attributes:
        entities: List of extracted entities
        relationships: List of inferred relationships
        metadata: Metadata about the ontology
        statistics: Optional statistics about the ontology
    """
    entities: List[Entity]
    relationships: List[Relationship]
    metadata: NotRequired[OntologyMetadata]
    statistics: NotRequired[Dict[str, Any]]


# ============================================================================
# Extraction Result Types
# ============================================================================


class EntityExtractionResult(TypedDict):
    """Result of entity extraction from a text document.
    
    Attributes:
        entities: List of extracted entities
        text: Source text that was processed
        confidence_scores: Per-entity confidence explanations
        extraction_method: Which method was used (rule_based, llm_based, hybrid)
        processing_time_ms: Time taken for extraction
    """
    entities: List[Entity]
    text: str
    confidence_scores: NotRequired[Dict[str, str]]
    extraction_method: NotRequired[str]
    processing_time_ms: NotRequired[float]


class RelationshipExtractionResult(TypedDict):
    """Result of relationship inference from extracted entities.
    
    Attributes:
        relationships: List of inferred relationships
        entity_pairs_analyzed: Number of entity pairs considered
        inference_method: Method used (co-occurrence, linguistic, rule_based)
        processing_time_ms: Time taken for inference
    """
    relationships: List[Relationship]
    entity_pairs_analyzed: NotRequired[int]
    inference_method: NotRequired[str]
    processing_time_ms: NotRequired[float]


# ============================================================================
# Critique and Evaluation Types
# ============================================================================


class DimensionalScore(TypedDict):
    """Score on a single quality dimension.
    
    Attributes:
        dimension_name: Name of the dimension (e.g., "completeness", "consistency")
        score: Score value (typically 0-1)
        explanation: Human-readable explanation
        recommendations: Optional list of improvement suggestions
    """
    dimension_name: str
    score: float
    explanation: str
    recommendations: NotRequired[List[str]]


class CriticRecommendation(TypedDict):
    """A specific recommendation for ontology improvement.
    
    Attributes:
        action: Type of action (e.g., "add_entity", "remove_relationship", "merge_entities")
        description: Human-readable description
        affected_ids: Entity/relationship IDs affected
        priority: Priority level (low, medium, high)
        estimated_impact: Estimated quality improvement if applied (0-1)
    """
    action: str
    description: str
    affected_ids: List[str]
    priority: NotRequired[Literal["low", "medium", "high"]]
    estimated_impact: NotRequired[float]


class CriticScore(TypedDict):
    """Complete evaluation results from the ontology critic.
    
    Attributes:
        overall: Overall quality score (0-1)
        dimensions: Individual dimension scores
        recommendations: List of improvement recommendations
        completeness: Completeness score (0-1)
        consistency: Consistency score (0-1)
        clarity: Clarity score (0-1)
        granularity: Granularity score (0-1)
        domain_alignment: Domain alignment score (0-1)
        relationship_coherence: Relationship coherence score (0-1)
        timestamp: ISO timestamp of evaluation
    """
    overall: float
    dimensions: NotRequired[List[DimensionalScore]]
    recommendations: NotRequired[List[CriticRecommendation]]
    completeness: NotRequired[float]
    consistency: NotRequired[float]
    clarity: NotRequired[float]
    granularity: NotRequired[float]
    domain_alignment: NotRequired[float]
    relationship_coherence: NotRequired[float]
    timestamp: NotRequired[str]


# ============================================================================
# Session and Context Types
# ============================================================================


class SessionRound(TypedDict):
    """A single round of the refinement cycle.
    
    Attributes:
        round_num: Round number (1-indexed)
        ontology: Generated ontology for this round
        score: Critic score for this round
        changes: Description of changes from previous round
    """
    round_num: int
    ontology: Ontology
    score: NotRequired[CriticScore]
    changes: NotRequired[str]


class OntologySession(TypedDict):
    """Session state for ontology generation and refinement.
    
    Attributes:
        session_id: Unique session identifier
        data_source: Source data being processed
        domain: Domain for generation
        current_round: Current refinement round number
        rounds: History of all rounds completed
        critic_scores: History of critic scores
        convergence_threshold: Convergence threshold for stopping
        start_time_ms: Session start time (milliseconds)
        end_time_ms: Session end time (milliseconds)
    """
    session_id: str
    data_source: str
    domain: str
    current_round: int
    rounds: NotRequired[List[SessionRound]]
    critic_scores: NotRequired[List[CriticScore]]
    convergence_threshold: NotRequired[float]
    start_time_ms: NotRequired[float]
    end_time_ms: NotRequired[float]


class GenerationContext(TypedDict):
    """Context for ontology generation.
    
    Attributes:
        data_source: Source data identifier
        data_type: Type of data (text, pdf, html, json)
        domain: Domain for domain-aware generation
        extraction_strategy: Strategy to use (rule_based, llm_based, hybrid)
        base_ontology: Optional base ontology to extend
        config: Extraction configuration parameters
    """
    data_source: str
    data_type: str
    domain: str
    extraction_strategy: NotRequired[str]
    base_ontology: NotRequired[Ontology]
    config: NotRequired[Dict[str, Any]]


# ============================================================================
# Statistics and Metrics Types
# ============================================================================


class EntityStatistics(TypedDict):
    """Statistics about extracted entities.
    
    Attributes:
        total_count: Total number of entities
        unique_types: Number of distinct entity types
        type_distribution: Count of entities per type
        confidence_mean: Mean confidence score
        confidence_min: Minimum confidence score
        confidence_max: Maximum confidence score
        confidence_distribution: Histogram of confidence scores
    """
    total_count: int
    unique_types: NotRequired[int]
    type_distribution: NotRequired[Dict[str, int]]
    confidence_mean: NotRequired[float]
    confidence_min: NotRequired[float]
    confidence_max: NotRequired[float]
    confidence_distribution: NotRequired[Dict[str, int]]


class RelationshipStatistics(TypedDict):
    """Statistics about inferred relationships.
    
    Attributes:
        total_count: Total number of relationships
        unique_types: Number of distinct relationship types
        type_distribution: Count of relationships per type
        confidence_mean: Mean confidence score
        confidence_min: Minimum confidence score
        confidence_max: Maximum confidence score
        density: Graph density (actual edges / possible edges)
        average_degree: Average node degree
    """
    total_count: int
    unique_types: NotRequired[int]
    type_distribution: NotRequired[Dict[str, int]]
    confidence_mean: NotRequired[float]
    confidence_min: NotRequired[float]
    confidence_max: NotRequired[float]
    density: NotRequired[float]
    average_degree: NotRequired[float]


class OntologyStatistics(TypedDict):
    """Complete statistics over an ontology.
    
    Attributes:
        entities: Entity statistics
        relationships: Relationship statistics
        graph_metrics: Optional graph theory metrics
        processing_time_ms: Time to generate ontology
    """
    entities: NotRequired[EntityStatistics]
    relationships: NotRequired[RelationshipStatistics]
    graph_metrics: NotRequired[Dict[str, Any]]
    processing_time_ms: NotRequired[float]


class PerformanceMetrics(TypedDict):
    """Performance metrics for optimization operations.
    
    Attributes:
        processing_time_ms: Time taken (milliseconds)
        memory_peak_mb: Peak memory usage (megabytes)
        entities_per_second: Extraction throughput
        relationships_per_second: Relationship inference throughput
    """
    processing_time_ms: float
    memory_peak_mb: NotRequired[float]
    entities_per_second: NotRequired[float]
    relationships_per_second: NotRequired[float]


class QualityMetrics(TypedDict):
    """Quality metrics for an ontology.
    
    Attributes:
        overall_score: Overall quality score (0-1)
        dimension_scores: Scores for each quality dimension
        test_pass_rate: Percentage of validation tests passed (0-1)
        coverage_ratio: Entities with relationships / total entities
    """
    overall_score: float
    dimension_scores: NotRequired[Dict[str, float]]
    test_pass_rate: NotRequired[float]
    coverage_ratio: NotRequired[float]


# ============================================================================
# Pipeline and Workflow Types
# ============================================================================


class PipelineStageResult(TypedDict):
    """Result from a single stage of the optimization pipeline.
    
    Attributes:
        stage_name: Name of the stage (generate, evaluate, optimize, validate)
        status: Success status (success, partial, failed)
        ontology: Generated/updated ontology
        score: Optional score if evaluation stage
        errors: List of any errors encountered
        warnings: List of any warnings
    """
    stage_name: str
    status: Literal["success", "partial", "failed"]
    ontology: NotRequired[Ontology]
    score: NotRequired[CriticScore]
    errors: NotRequired[List[str]]
    warnings: NotRequired[List[str]]


class RefinementCycleResult(TypedDict):
    """Result of a complete refinement cycle.
    
    Attributes:
        session_id: Session identifier
        initial_ontology: Starting ontology
        final_ontology: Final optimized ontology
        rounds_completed: Number of rounds completed
        convergence_achieved: Whether convergence criteria were met
        initial_score: Score before refinement
        final_score: Score after refinement
        improvement: Improvement percentage
    """
    session_id: str
    initial_ontology: NotRequired[Ontology]
    final_ontology: Ontology
    rounds_completed: int
    convergence_achieved: bool
    initial_score: NotRequired[CriticScore]
    final_score: CriticScore
    improvement: NotRequired[float]


# ============================================================================
# Configuration and Settings Types
# ============================================================================


class ExtractionConfigDict(TypedDict):
    """Configuration for entity/relationship extraction.
    
    Attributes:
        confidence_threshold: Minimum confidence to keep entities (0-1)
        max_entities: Maximum entities per run (0 = unlimited)
        max_relationships: Maximum relationships per run (0 = unlimited)
        window_size: Co-occurrence window size for relationship inference
        include_properties: Include property predicates
        domain_vocab: Domain-specific vocabulary
        min_entity_length: Minimum entity text length
        max_confidence: Maximum confidence score (0-1]
        allowed_entity_types: Whitelist of entity types (empty = allow all)
        stopwords: List of words to skip
        custom_rules: Custom extraction rules
        llm_fallback_threshold: LLM fallback threshold
    """
    confidence_threshold: NotRequired[float]
    max_entities: NotRequired[int]
    max_relationships: NotRequired[int]
    window_size: NotRequired[int]
    include_properties: NotRequired[bool]
    domain_vocab: NotRequired[Dict[str, List[str]]]
    min_entity_length: NotRequired[int]
    max_confidence: NotRequired[float]
    allowed_entity_types: NotRequired[List[str]]
    stopwords: NotRequired[List[str]]
    custom_rules: NotRequired[List[Tuple[str, str]]]
    llm_fallback_threshold: NotRequired[float]


class OptimizerConfig(TypedDict):
    """Configuration for an ontology optimizer.
    
    Attributes:
        domain: Domain for generation
        max_rounds: Maximum refinement rounds
        convergence_threshold: Convergence score threshold
        extraction_config: Extraction configuration
        generation_strategy: Entity extraction strategy
        validation_level: Validation rigor level
    """
    domain: str
    max_rounds: NotRequired[int]
    convergence_threshold: NotRequired[float]
    extraction_config: NotRequired[ExtractionConfigDict]
    generation_strategy: NotRequired[str]
    validation_level: NotRequired[Literal["basic", "standard", "strict", "paranoid"]]
