"""
Ontology Critic for GraphRAG Optimization.

This module provides an LLM-based critic that evaluates knowledge graph ontology
quality across multiple dimensions. Inspired by the critic agent from the
complaint-generator adversarial harness.

The critic analyzes ontologies and provides structured feedback with scores across
multiple evaluation dimensions, along with actionable recommendations for improvement.

Key Features:
    - Multi-dimensional ontology evaluation
    - Structured scoring with weighted dimensions
    - Actionable recommendations for improvement
    - Comparison between ontologies
    - Domain-aware evaluation

Evaluation Dimensions:
    - Completeness (25%): Coverage of key concepts and relationships
    - Consistency (25%): Internal logical consistency
    - Clarity (15%): Clear entity definitions and relationships
    - Granularity (15%): Appropriate level of detail
    - Domain Alignment (20%): Adherence to domain conventions

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyCritic,
    ...     OntologyGenerationContext
    ... )
    >>> 
    >>> critic = OntologyCritic(backend_config={
    ...     'model': 'gpt-4',
    ...     'temperature': 0.3
    ... })
    >>> 
    >>> score = critic.evaluate_ontology(
    ...     ontology=ontology,
    ...     context=context,
    ...     source_data=data
    ... )
    >>> 
    >>> print(f"Overall: {score.overall}, Completeness: {score.completeness}")

References:
    - complaint-generator critic.py: Multi-dimensional evaluation patterns
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Evaluation dimension weights (must sum to 1.0)
DIMENSION_WEIGHTS = {
    'completeness': 0.25,
    'consistency': 0.25,
    'clarity': 0.15,
    'granularity': 0.15,
    'domain_alignment': 0.20,
}


@dataclass
class CriticScore:
    """
    Structured ontology quality score.
    
    Provides a comprehensive evaluation of an ontology across multiple dimensions,
    with weighted overall score and actionable feedback.
    
    Attributes:
        overall: Overall quality score (0.0 to 1.0), weighted average of dimensions
        completeness: Coverage of key concepts and relationships (0.0 to 1.0)
        consistency: Internal logical consistency (0.0 to 1.0)
        clarity: Clarity of entity definitions and relationships (0.0 to 1.0)
        granularity: Appropriateness of detail level (0.0 to 1.0)
        domain_alignment: Adherence to domain conventions (0.0 to 1.0)
        strengths: List of ontology strengths
        weaknesses: List of ontology weaknesses
        recommendations: Actionable recommendations for improvement
        metadata: Additional evaluation metadata
        
    Example:
        >>> score = CriticScore(
        ...     completeness=0.85,
        ...     consistency=0.90,
        ...     clarity=0.75,
        ...     granularity=0.80,
        ...     domain_alignment=0.88
        ... )
        >>> print(f"Overall: {score.overall:.2f}")
    """
    
    completeness: float
    consistency: float
    clarity: float
    granularity: float
    domain_alignment: float
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def overall(self) -> float:
        """
        Calculate weighted overall score.
        
        Returns:
            Overall score as weighted average of dimension scores
        """
        return (
            DIMENSION_WEIGHTS['completeness'] * self.completeness +
            DIMENSION_WEIGHTS['consistency'] * self.consistency +
            DIMENSION_WEIGHTS['clarity'] * self.clarity +
            DIMENSION_WEIGHTS['granularity'] * self.granularity +
            DIMENSION_WEIGHTS['domain_alignment'] * self.domain_alignment
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert score to dictionary representation.
        
        Returns:
            Dictionary with all score components and feedback
        """
        return {
            'overall': self.overall,
            'dimensions': {
                'completeness': self.completeness,
                'consistency': self.consistency,
                'clarity': self.clarity,
                'granularity': self.granularity,
                'domain_alignment': self.domain_alignment,
            },
            'weights': DIMENSION_WEIGHTS,
            'strengths': self.strengths,
            'weaknesses': self.weaknesses,
            'recommendations': self.recommendations,
            'metadata': self.metadata,
        }


class OntologyCritic:
    """
    LLM-based critic for evaluating ontology quality.
    
    This class provides comprehensive ontology evaluation across multiple dimensions,
    inspired by the critic agent from complaint-generator. It can evaluate single
    ontologies or compare multiple ontologies.
    
    The critic uses an LLM backend to perform semantic evaluation of ontology quality,
    providing structured scores and actionable recommendations.
    
    Attributes:
        backend_config: Configuration for LLM backend
        use_llm: Whether to use LLM for evaluation
        
    Example:
        >>> critic = OntologyCritic(backend_config={
        ...     'provider': 'openai',
        ...     'model': 'gpt-4',
        ...     'temperature': 0.3
        ... })
        >>> 
        >>> score = critic.evaluate_ontology(ontology, context, data)
        >>> if score.overall < 0.7:
        ...     print("Needs improvement:", score.recommendations)
    """
    
    def __init__(
        self,
        backend_config: Optional[Dict[str, Any]] = None,
        use_llm: bool = True
    ):
        """
        Initialize the ontology critic.
        
        Args:
            backend_config: Configuration for LLM backend. Should include
                'provider' (e.g., 'openai', 'anthropic'), 'model', and
                optionally 'temperature', 'max_tokens', etc.
            use_llm: Whether to use LLM for evaluation. If False, uses
                rule-based heuristics.
                
        Raises:
            ImportError: If LLM backend is required but not available
        """
        self.backend_config = backend_config or {}
        self.use_llm = use_llm
        self._llm_client = None
        
        if use_llm:
            try:
                # Try to import LLM backend
                # TODO: Implement LLM backend integration in Phase 1
                self._llm_available = False
                logger.info("LLM backend integration (placeholder)")
            except ImportError as e:
                logger.warning(
                    f"LLM backend not available: {e}. "
                    "Falling back to rule-based evaluation."
                )
                self._llm_available = False
                self.use_llm = False
        else:
            self._llm_available = False
    
    def evaluate_ontology(
        self,
        ontology: Dict[str, Any],
        context: Any,  # OntologyGenerationContext
        source_data: Optional[Any] = None
    ) -> CriticScore:
        """
        Evaluate ontology across all quality dimensions.
        
        Performs comprehensive evaluation of an ontology, analyzing completeness,
        consistency, clarity, granularity, and domain alignment. Returns a
        structured score with actionable recommendations.
        
        Args:
            ontology: Ontology to evaluate (dictionary format)
            context: Context with domain and configuration information
            source_data: Optional source data for context-aware evaluation
            
        Returns:
            CriticScore with evaluation results and recommendations
            
        Example:
            >>> score = critic.evaluate_ontology(
            ...     ontology={'entities': [...], 'relationships': [...]},
            ...     context=generation_context,
            ...     source_data="Original document text..."
            ... )
            >>> print(f"Score: {score.overall:.2f}")
            >>> for rec in score.recommendations:
            ...     print(f"- {rec}")
        """
        logger.info("Evaluating ontology quality")
        
        # Evaluate each dimension
        completeness = self._evaluate_completeness(ontology, context, source_data)
        consistency = self._evaluate_consistency(ontology, context)
        clarity = self._evaluate_clarity(ontology, context)
        granularity = self._evaluate_granularity(ontology, context)
        domain_alignment = self._evaluate_domain_alignment(ontology, context)
        
        # Identify strengths and weaknesses
        strengths = self._identify_strengths(
            completeness, consistency, clarity, granularity, domain_alignment
        )
        weaknesses = self._identify_weaknesses(
            completeness, consistency, clarity, granularity, domain_alignment
        )
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            ontology, context, completeness, consistency, clarity,
            granularity, domain_alignment
        )
        
        # Create score
        score = CriticScore(
            completeness=completeness,
            consistency=consistency,
            clarity=clarity,
            granularity=granularity,
            domain_alignment=domain_alignment,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
            metadata={
                'evaluator': 'OntologyCritic',
                'use_llm': self.use_llm,
                'domain': getattr(context, 'domain', 'unknown')
            }
        )
        
        logger.info(f"Evaluation complete. Overall score: {score.overall:.2f}")
        return score
    
    def compare_ontologies(
        self,
        ontology1: Dict[str, Any],
        ontology2: Dict[str, Any],
        context: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Compare two ontologies and identify improvements.
        
        Evaluates both ontologies and provides a comparative analysis,
        highlighting which ontology performs better in each dimension
        and identifying specific improvements.
        
        Args:
            ontology1: First ontology to compare
            ontology2: Second ontology to compare
            context: Optional context for evaluation
            
        Returns:
            Dictionary with comparative analysis:
                - 'score1': Score for ontology1
                - 'score2': Score for ontology2
                - 'better': Which ontology is better overall
                - 'improvements': List of specific improvements in better ontology
                - 'regressions': List of specific regressions
                
        Example:
            >>> comparison = critic.compare_ontologies(old_ontology, new_ontology)
            >>> if comparison['better'] == 'ontology2':
            ...     print("New ontology is better!")
            ...     print("Improvements:", comparison['improvements'])
        """
        logger.info("Comparing two ontologies")
        
        # Evaluate both ontologies
        score1 = self.evaluate_ontology(ontology1, context) if context else None
        score2 = self.evaluate_ontology(ontology2, context) if context else None
        
        # Determine which is better
        better = 'ontology2' if (score2 and score1 and score2.overall > score1.overall) else 'ontology1'
        
        # Identify improvements and regressions
        improvements = []
        regressions = []
        
        if score1 and score2:
            dimensions = ['completeness', 'consistency', 'clarity', 'granularity', 'domain_alignment']
            for dim in dimensions:
                val1 = getattr(score1, dim)
                val2 = getattr(score2, dim)
                if val2 > val1:
                    improvements.append(f"{dim}: {val1:.2f} → {val2:.2f}")
                elif val2 < val1:
                    regressions.append(f"{dim}: {val1:.2f} → {val2:.2f}")
        
        return {
            'score1': score1.to_dict() if score1 else None,
            'score2': score2.to_dict() if score2 else None,
            'better': better,
            'improvements': improvements,
            'regressions': regressions,
        }
    
    def _evaluate_completeness(
        self,
        ontology: Dict[str, Any],
        context: Any,
        source_data: Optional[Any]
    ) -> float:
        """
        Evaluate completeness of ontology.
        
        Assesses how well the ontology covers key concepts and relationships
        in the domain and source data.
        
        Args:
            ontology: Ontology to evaluate
            context: Generation context
            source_data: Optional source data
            
        Returns:
            Completeness score (0.0 to 1.0)
        """
        # TODO: Implement sophisticated completeness evaluation
        # This is a placeholder for Phase 1 implementation
        
        # Basic heuristic: check if we have entities and relationships
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])
        
        if not entities:
            return 0.0
        
        # Simple heuristic based on entity and relationship counts
        entity_score = min(len(entities) / 10.0, 1.0)  # Assume 10 entities is "complete"
        relationship_score = min(len(relationships) / len(entities), 1.0) if entities else 0.0
        
        return (entity_score + relationship_score) / 2.0
    
    def _evaluate_consistency(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate internal logical consistency.
        
        Checks for contradictions, circular dependencies, and other
        consistency issues in the ontology structure.
        
        Args:
            ontology: Ontology to evaluate
            context: Generation context
            
        Returns:
            Consistency score (0.0 to 1.0)
        """
        # TODO: Implement consistency checking
        # This is a placeholder for Phase 1 implementation
        
        # For now, check basic structural consistency
        entities = ontology.get('entities', [])
        relationships = ontology.get('relationships', [])
        
        # Check that all relationships reference valid entities
        entity_ids = {e.get('id') for e in entities if isinstance(e, dict)}
        
        invalid_refs = 0
        for rel in relationships:
            if isinstance(rel, dict):
                if rel.get('source_id') not in entity_ids:
                    invalid_refs += 1
                if rel.get('target_id') not in entity_ids:
                    invalid_refs += 1
        
        if not relationships:
            return 1.0
        
        # Score based on valid references
        return max(0.0, 1.0 - (invalid_refs / (len(relationships) * 2)))
    
    def _evaluate_clarity(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate clarity of entity definitions and relationships.
        
        Args:
            ontology: Ontology to evaluate
            context: Generation context
            
        Returns:
            Clarity score (0.0 to 1.0)
        """
        # TODO: Implement clarity evaluation
        # This is a placeholder for Phase 1 implementation
        
        entities = ontology.get('entities', [])
        
        if not entities:
            return 0.0
        
        # Simple heuristic: entities with properties are clearer
        with_properties = sum(
            1 for e in entities
            if isinstance(e, dict) and e.get('properties')
        )
        
        return with_properties / len(entities) if entities else 0.0
    
    def _evaluate_granularity(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate appropriateness of detail level.
        
        Args:
            ontology: Ontology to evaluate
            context: Generation context
            
        Returns:
            Granularity score (0.0 to 1.0)
        """
        # TODO: Implement granularity evaluation
        # This is a placeholder for Phase 1 implementation
        
        # For now, assume reasonable granularity
        return 0.75
    
    def _evaluate_domain_alignment(
        self,
        ontology: Dict[str, Any],
        context: Any
    ) -> float:
        """
        Evaluate adherence to domain conventions.
        
        Args:
            ontology: Ontology to evaluate
            context: Generation context
            
        Returns:
            Domain alignment score (0.0 to 1.0)
        """
        # TODO: Implement domain-specific evaluation
        # This is a placeholder for Phase 1 implementation
        
        # For now, assume reasonable domain alignment
        return 0.80
    
    def _identify_strengths(
        self,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
        domain_alignment: float
    ) -> List[str]:
        """Identify ontology strengths based on dimension scores."""
        strengths = []
        
        threshold = 0.8
        
        if completeness >= threshold:
            strengths.append("Comprehensive entity and relationship coverage")
        if consistency >= threshold:
            strengths.append("Strong internal logical consistency")
        if clarity >= threshold:
            strengths.append("Clear and well-defined entities")
        if granularity >= threshold:
            strengths.append("Appropriate level of detail")
        if domain_alignment >= threshold:
            strengths.append("Good adherence to domain conventions")
        
        return strengths
    
    def _identify_weaknesses(
        self,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
        domain_alignment: float
    ) -> List[str]:
        """Identify ontology weaknesses based on dimension scores."""
        weaknesses = []
        
        threshold = 0.6
        
        if completeness < threshold:
            weaknesses.append("Incomplete coverage of key concepts")
        if consistency < threshold:
            weaknesses.append("Logical inconsistencies detected")
        if clarity < threshold:
            weaknesses.append("Unclear or ambiguous entity definitions")
        if granularity < threshold:
            weaknesses.append("Inappropriate level of detail")
        if domain_alignment < threshold:
            weaknesses.append("Poor alignment with domain conventions")
        
        return weaknesses
    
    def _generate_recommendations(
        self,
        ontology: Dict[str, Any],
        context: Any,
        completeness: float,
        consistency: float,
        clarity: float,
        granularity: float,
        domain_alignment: float
    ) -> List[str]:
        """Generate actionable recommendations for improvement."""
        recommendations = []
        
        # Prioritize based on lowest scores
        scores = [
            (completeness, "completeness"),
            (consistency, "consistency"),
            (clarity, "clarity"),
            (granularity, "granularity"),
            (domain_alignment, "domain_alignment")
        ]
        
        # Sort by score (lowest first)
        sorted_scores = sorted(scores, key=lambda x: x[0])
        
        # Generate recommendations for lowest scoring dimensions
        for score, dimension in sorted_scores[:3]:  # Top 3 areas for improvement
            if score < 0.7:
                if dimension == "completeness":
                    recommendations.append(
                        "Add more entities and relationships to improve coverage"
                    )
                elif dimension == "consistency":
                    recommendations.append(
                        "Review and fix logical inconsistencies in relationships"
                    )
                elif dimension == "clarity":
                    recommendations.append(
                        "Add more properties and descriptions to entities"
                    )
                elif dimension == "granularity":
                    recommendations.append(
                        "Adjust the level of detail to be more appropriate"
                    )
                elif dimension == "domain_alignment":
                    recommendations.append(
                        "Better align entity types with domain conventions"
                    )
        
        return recommendations


# Export public API
__all__ = [
    'OntologyCritic',
    'CriticScore',
    'DIMENSION_WEIGHTS',
]
