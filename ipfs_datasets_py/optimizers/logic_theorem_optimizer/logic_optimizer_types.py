"""Typed return contracts for logic theorem optimizer API.

Provides typed definitions for all public method return values,
replacing ambiguous `Dict[str, Any]` with structured TypedDict classes.
"""

from typing import Any, Dict, List, Optional, TypedDict


class FormulaTranslation(TypedDict, total=False):
    """Translation result from natural language to TDFOL."""
    original_text: str
    tdfol_formula: str
    variables: List[str]
    translation_confidence: float
    alternative_formulas: List[str]


class ProverResult(TypedDict, total=False):
    """Result of theorem proving."""
    is_provable: bool
    proof_steps: List[str]
    proof_length: int
    execution_time_ms: float
    prover_name: str
    confidence: float
    counterexample: Optional[Any]


class ValidationStatus(TypedDict, total=False):
    """Status of ontology validation against TDFOL."""
    is_consistent: bool
    contradictions: List[str]
    unresolvable_formulas: List[str]
    validation_time_ms: float
    coverage_percentage: float
    coverage_details: Dict[str, Any]


class ConflictResolution(TypedDict, total=False):
    """Result of conflict resolution."""
    conflict_type: str  # e.g., "semantic", "structural", "semantic_structural"
    original_entities: List[str]
    resolution_strategy: str
    merged_entity: Optional[str]
    merged_relationships: List[str]
    resolution_confidence: float
    execution_time_ms: float


class OntologyEvolutionStep(TypedDict, total=False):
    """Single step in ontology evolution."""
    step_number: int
    action: str  # e.g., "add_constraints", "refine_types", "expand_kb"
    changes_applied: List[str]
    consistency_maintained: bool
    quality_change: float
    execution_time_ms: float


class NeuralSymbolicProofResult(TypedDict, total=False):
    """Result from neural-symbolic prover."""
    formula: str
    neural_score: float
    symbolic_success: bool
    hybrid_confidence: float
    execution_time_ms: float
    reasoning_path: List[str]
    fallback_used: bool


class LogicExtractorResult(TypedDict, total=False):
    """Result of logic extraction from text."""
    formulas: List[str]
    variables: List[str]
    predicates: List[str]
    extraction_confidence: float
    suggested_domains: List[str]
    execution_time_ms: float


class TheoryConsistencyCheck(TypedDict, total=False):
    """Consistency check for a theory."""
    is_consistent: bool
    contradiction_found: Optional[str]
    proof_by_contradiction: Optional[List[str]]
    circular_dependencies: List[str]
    execution_time_ms: float
    confidence: float


class LogicOptimizationMetrics(TypedDict, total=False):
    """Metrics for logic optimization round."""
    initial_formula_count: int
    final_formula_count: int
    optimizations_applied: int
    redundancy_eliminated: int
    simplifications_made: int
    total_execution_time_ms: float
    quality_improvement: float
    maintainability_score: float


class DisributedProofResult(TypedDict, total=False):
    """Result of distributed proof processing."""
    total_processes: int
    successful_proofs: int
    failed_proofs: int
    average_proof_time_ms: float
    max_proof_time_ms: float
    min_proof_time_ms: float
    total_execution_time_ms: float
    load_balance_factor: float


class KGIntegrationResult(TypedDict, total=False):
    """Result of knowledge graph integration."""
    formulas_grounded: int
    entities_linked: int
    relationships_linked: int
    grounding_confidence_avg: float
    ungroundable_formulas: List[str]
    integration_time_ms: float


class RAGIntegrationResult(TypedDict, total=False):
    """Result of RAG (Retrieval-Augmented Generation) integration."""
    retrieved_documents: int
    relevant_facts: int
    facts_incorporated: int
    augmentation_quality: float
    reasoning_enhanced: bool
    integration_time_ms: float


__all__ = [
    "FormulaTranslation",
    "ProverResult",
    "ValidationStatus",
    "ConflictResolution",
    "OntologyEvolutionStep",
    "NeuralSymbolicProofResult",
    "LogicExtractorResult",
    "TheoryConsistencyCheck",
    "LogicOptimizationMetrics",
    "DisributedProofResult",
    "KGIntegrationResult",
    "RAGIntegrationResult",
]
