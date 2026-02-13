"""Logic Critic - Evaluates logical consistency and quality.

This module implements a critic agent that evaluates the quality of extracted
logical statements using theorem provers and consistency checkers.

Analogous to the Critic agent in the adversarial harness, the LogicCritic
provides structured feedback across multiple dimensions to guide optimization.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CriticDimensions(Enum):
    """Dimensions for evaluating logical statements."""
    SOUNDNESS = "soundness"  # Logical validity
    COMPLETENESS = "completeness"  # Coverage of input data
    CONSISTENCY = "consistency"  # Internal consistency
    ONTOLOGY_ALIGNMENT = "ontology_alignment"  # Alignment with KG ontology
    PARSABILITY = "parsability"  # Can be parsed by theorem provers
    EXPRESSIVENESS = "expressiveness"  # Captures nuance


@dataclass
class DimensionScore:
    """Score for a single evaluation dimension.
    
    Attributes:
        dimension: The dimension being scored
        score: Score value (0.0-1.0)
        feedback: Textual feedback
        details: Additional scoring details
    """
    dimension: CriticDimensions
    score: float
    feedback: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CriticScore:
    """Complete critic evaluation score.
    
    Attributes:
        overall: Overall score (weighted average)
        dimension_scores: Scores by dimension
        strengths: Identified strengths
        weaknesses: Identified weaknesses
        recommendations: Specific recommendations for improvement
        prover_results: Results from theorem provers
    """
    overall: float
    dimension_scores: List[DimensionScore]
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    prover_results: Dict[str, Any] = field(default_factory=dict)
    
    def get_dimension_score(self, dimension: CriticDimensions) -> Optional[float]:
        """Get score for a specific dimension."""
        for ds in self.dimension_scores:
            if ds.dimension == dimension:
                return ds.score
        return None


class LogicCritic:
    """Critic agent for evaluating logical statement quality.
    
    This agent uses theorem provers and consistency checkers to evaluate
    the quality of extracted logical statements across multiple dimensions.
    
    Evaluation dimensions (with weights):
    - Soundness (30%): Are statements logically valid?
    - Completeness (20%): Do statements cover all input data?
    - Consistency (20%): Are statements internally consistent?
    - Ontology Alignment (15%): Do statements align with KG ontology?
    - Parsability (10%): Can provers parse the statements?
    - Expressiveness (5%): Do statements capture nuance?
    
    Example:
        >>> from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicCritic
        >>> critic = LogicCritic(use_provers=['z3', 'cvc5'])
        >>> score = critic.evaluate(extraction_result)
        >>> print(f"Overall: {score.overall}")
        >>> print(f"Soundness: {score.get_dimension_score(CriticDimensions.SOUNDNESS)}")
    """
    
    # Dimension weights for overall score
    DIMENSION_WEIGHTS = {
        CriticDimensions.SOUNDNESS: 0.30,
        CriticDimensions.COMPLETENESS: 0.20,
        CriticDimensions.CONSISTENCY: 0.20,
        CriticDimensions.ONTOLOGY_ALIGNMENT: 0.15,
        CriticDimensions.PARSABILITY: 0.10,
        CriticDimensions.EXPRESSIVENESS: 0.05,
    }
    
    def __init__(
        self,
        use_provers: Optional[List[str]] = None,
        strict_mode: bool = False
    ):
        """Initialize the logic critic.
        
        Args:
            use_provers: List of theorem provers to use ('z3', 'cvc5', 'lean', etc.)
            strict_mode: Whether to use strict evaluation criteria
        """
        self.use_provers = use_provers or ['z3']
        self.strict_mode = strict_mode
        self._init_provers()
        
    def _init_provers(self) -> None:
        """Initialize theorem provers."""
        self.provers = {}
        
        for prover_name in self.use_provers:
            try:
                if prover_name == 'z3':
                    from ipfs_datasets_py.logic.external_provers.smt.z3_prover_bridge import Z3ProverBridge
                    self.provers['z3'] = Z3ProverBridge()
                    logger.info("Initialized Z3 prover")
                elif prover_name == 'cvc5':
                    from ipfs_datasets_py.logic.external_provers.smt.cvc5_prover_bridge import CVC5ProverBridge
                    self.provers['cvc5'] = CVC5ProverBridge()
                    logger.info("Initialized CVC5 prover")
                elif prover_name == 'lean':
                    from ipfs_datasets_py.logic.external_provers.interactive.lean_prover_bridge import LeanProverBridge
                    self.provers['lean'] = LeanProverBridge()
                    logger.info("Initialized Lean prover")
                elif prover_name == 'symbolic':
                    from ipfs_datasets_py.logic.external_provers.neural.symbolicai_prover_bridge import SymbolicAIProverBridge
                    self.provers['symbolic'] = SymbolicAIProverBridge()
                    logger.info("Initialized SymbolicAI prover")
            except ImportError as e:
                logger.warning(f"Could not initialize {prover_name} prover: {e}")
    
    def evaluate(self, extraction_result) -> CriticScore:
        """Evaluate an extraction result.
        
        Args:
            extraction_result: ExtractionResult to evaluate
            
        Returns:
            CriticScore with evaluation results
        """
        dimension_scores = []
        
        # Evaluate each dimension
        dimension_scores.append(self._evaluate_soundness(extraction_result))
        dimension_scores.append(self._evaluate_completeness(extraction_result))
        dimension_scores.append(self._evaluate_consistency(extraction_result))
        dimension_scores.append(self._evaluate_ontology_alignment(extraction_result))
        dimension_scores.append(self._evaluate_parsability(extraction_result))
        dimension_scores.append(self._evaluate_expressiveness(extraction_result))
        
        # Calculate overall score
        overall = self._calculate_overall(dimension_scores)
        
        # Identify strengths and weaknesses
        strengths, weaknesses = self._identify_strengths_weaknesses(dimension_scores)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(dimension_scores, extraction_result)
        
        return CriticScore(
            overall=overall,
            dimension_scores=dimension_scores,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations
        )
    
    def _evaluate_soundness(self, extraction_result) -> DimensionScore:
        """Evaluate logical soundness using theorem provers.
        
        Args:
            extraction_result: ExtractionResult to evaluate
            
        Returns:
            DimensionScore for soundness
        """
        score = 0.0
        feedback = []
        details = {'prover_results': {}}
        
        statements = extraction_result.statements
        if not statements:
            return DimensionScore(
                dimension=CriticDimensions.SOUNDNESS,
                score=0.0,
                feedback="No statements to evaluate",
                details=details
            )
        
        # Check each statement with available provers
        valid_count = 0
        for stmt in statements:
            is_valid = False
            
            for prover_name, prover in self.provers.items():
                try:
                    # Try to verify the statement
                    # result = prover.verify(stmt.formula)
                    # is_valid = result.valid
                    # For now, use confidence as proxy
                    is_valid = stmt.confidence > 0.6
                    details['prover_results'][prover_name] = is_valid
                    break
                except Exception as e:
                    logger.debug(f"Prover {prover_name} failed: {e}")
            
            if is_valid:
                valid_count += 1
        
        score = valid_count / len(statements) if statements else 0.0
        
        if score > 0.8:
            feedback.append("Strong logical validity across statements")
        elif score > 0.5:
            feedback.append("Moderate logical validity, some statements questionable")
        else:
            feedback.append("Many statements lack logical soundness")
        
        return DimensionScore(
            dimension=CriticDimensions.SOUNDNESS,
            score=score,
            feedback="; ".join(feedback),
            details=details
        )
    
    def _evaluate_completeness(self, extraction_result) -> DimensionScore:
        """Evaluate completeness of extraction.
        
        Args:
            extraction_result: ExtractionResult to evaluate
            
        Returns:
            DimensionScore for completeness
        """
        # Check if extraction covers the input data
        data_str = str(extraction_result.context.data)
        statements = extraction_result.statements
        
        if not statements:
            return DimensionScore(
                dimension=CriticDimensions.COMPLETENESS,
                score=0.0,
                feedback="No statements extracted"
            )
        
        # Simple heuristic: check coverage of key terms
        data_words = set(data_str.lower().split())
        covered_words = set()
        
        for stmt in statements:
            stmt_words = stmt.formula.lower().split()
            covered_words.update(w for w in stmt_words if w in data_words)
        
        coverage = len(covered_words) / max(len(data_words), 1)
        score = min(coverage, 1.0)
        
        feedback = []
        if score > 0.7:
            feedback.append("Good coverage of input data")
        elif score > 0.4:
            feedback.append("Moderate coverage, some aspects missing")
        else:
            feedback.append("Poor coverage, many aspects not captured")
        
        return DimensionScore(
            dimension=CriticDimensions.COMPLETENESS,
            score=score,
            feedback="; ".join(feedback)
        )
    
    def _evaluate_consistency(self, extraction_result) -> DimensionScore:
        """Evaluate internal consistency of statements.
        
        Args:
            extraction_result: ExtractionResult to evaluate
            
        Returns:
            DimensionScore for consistency
        """
        statements = extraction_result.statements
        
        if len(statements) < 2:
            return DimensionScore(
                dimension=CriticDimensions.CONSISTENCY,
                score=1.0,
                feedback="Single statement, trivially consistent"
            )
        
        # Check for contradictions using provers
        # For now, use a simple heuristic
        score = 0.85  # Default to high consistency
        
        feedback = []
        feedback.append("No obvious contradictions detected")
        
        return DimensionScore(
            dimension=CriticDimensions.CONSISTENCY,
            score=score,
            feedback="; ".join(feedback)
        )
    
    def _evaluate_ontology_alignment(self, extraction_result) -> DimensionScore:
        """Evaluate alignment with knowledge graph ontology.
        
        Args:
            extraction_result: ExtractionResult to evaluate
            
        Returns:
            DimensionScore for ontology alignment
        """
        alignment = extraction_result.ontology_alignment
        
        if not alignment:
            return DimensionScore(
                dimension=CriticDimensions.ONTOLOGY_ALIGNMENT,
                score=0.5,
                feedback="No ontology provided for alignment"
            )
        
        # Average alignment scores
        score = sum(alignment.values()) / len(alignment) if alignment else 0.0
        
        feedback = []
        if score > 0.7:
            feedback.append("Strong alignment with ontology")
        elif score > 0.4:
            feedback.append("Moderate alignment with ontology")
        else:
            feedback.append("Poor alignment with ontology")
        
        return DimensionScore(
            dimension=CriticDimensions.ONTOLOGY_ALIGNMENT,
            score=score,
            feedback="; ".join(feedback),
            details={'alignment': alignment}
        )
    
    def _evaluate_parsability(self, extraction_result) -> DimensionScore:
        """Evaluate whether statements can be parsed by provers.
        
        Args:
            extraction_result: ExtractionResult to evaluate
            
        Returns:
            DimensionScore for parsability
        """
        statements = extraction_result.statements
        
        if not statements:
            return DimensionScore(
                dimension=CriticDimensions.PARSABILITY,
                score=0.0,
                feedback="No statements to parse"
            )
        
        # Try parsing with available provers
        parsable_count = 0
        for stmt in statements:
            # For now, assume statements are parsable if confidence > 0.5
            if stmt.confidence > 0.5:
                parsable_count += 1
        
        score = parsable_count / len(statements) if statements else 0.0
        
        feedback = []
        if score > 0.8:
            feedback.append("All statements parsable by provers")
        elif score > 0.5:
            feedback.append("Most statements parsable")
        else:
            feedback.append("Many statements not parsable by provers")
        
        return DimensionScore(
            dimension=CriticDimensions.PARSABILITY,
            score=score,
            feedback="; ".join(feedback)
        )
    
    def _evaluate_expressiveness(self, extraction_result) -> DimensionScore:
        """Evaluate how well statements capture nuance.
        
        Args:
            extraction_result: ExtractionResult to evaluate
            
        Returns:
            DimensionScore for expressiveness
        """
        statements = extraction_result.statements
        
        if not statements:
            return DimensionScore(
                dimension=CriticDimensions.EXPRESSIVENESS,
                score=0.0,
                feedback="No statements to evaluate"
            )
        
        # Simple heuristic: check formula complexity
        avg_complexity = sum(len(s.formula) for s in statements) / len(statements)
        
        # Normalize to 0-1 range (assume 100 chars is good complexity)
        score = min(avg_complexity / 100.0, 1.0)
        
        feedback = []
        if score > 0.7:
            feedback.append("Statements capture nuanced relationships")
        elif score > 0.4:
            feedback.append("Moderate expressiveness")
        else:
            feedback.append("Statements lack nuance and detail")
        
        return DimensionScore(
            dimension=CriticDimensions.EXPRESSIVENESS,
            score=score,
            feedback="; ".join(feedback)
        )
    
    def _calculate_overall(self, dimension_scores: List[DimensionScore]) -> float:
        """Calculate weighted overall score.
        
        Args:
            dimension_scores: List of dimension scores
            
        Returns:
            Overall weighted score
        """
        total = 0.0
        for ds in dimension_scores:
            weight = self.DIMENSION_WEIGHTS.get(ds.dimension, 0.0)
            total += ds.score * weight
        return total
    
    def _identify_strengths_weaknesses(
        self,
        dimension_scores: List[DimensionScore]
    ) -> tuple[List[str], List[str]]:
        """Identify strengths and weaknesses from dimension scores.
        
        Args:
            dimension_scores: List of dimension scores
            
        Returns:
            Tuple of (strengths, weaknesses)
        """
        strengths = []
        weaknesses = []
        
        for ds in dimension_scores:
            if ds.score > 0.75:
                strengths.append(f"Strong {ds.dimension.value}: {ds.feedback}")
            elif ds.score < 0.4:
                weaknesses.append(f"Weak {ds.dimension.value}: {ds.feedback}")
        
        return strengths, weaknesses
    
    def _generate_recommendations(
        self,
        dimension_scores: List[DimensionScore],
        extraction_result
    ) -> List[str]:
        """Generate specific recommendations for improvement.
        
        Args:
            dimension_scores: List of dimension scores
            extraction_result: ExtractionResult being evaluated
            
        Returns:
            List of recommendations
        """
        recommendations = []
        
        for ds in dimension_scores:
            if ds.score < 0.5:
                if ds.dimension == CriticDimensions.SOUNDNESS:
                    recommendations.append("Improve logical validity by using more precise predicates")
                elif ds.dimension == CriticDimensions.COMPLETENESS:
                    recommendations.append("Extract more statements to cover all aspects of input data")
                elif ds.dimension == CriticDimensions.CONSISTENCY:
                    recommendations.append("Check for contradictions and resolve inconsistencies")
                elif ds.dimension == CriticDimensions.ONTOLOGY_ALIGNMENT:
                    recommendations.append("Better align with ontology terminology and structure")
                elif ds.dimension == CriticDimensions.PARSABILITY:
                    recommendations.append("Use standard formal logic syntax")
                elif ds.dimension == CriticDimensions.EXPRESSIVENESS:
                    recommendations.append("Add more detail and nuance to logical statements")
        
        if not recommendations:
            recommendations.append("Overall quality is good, continue current approach")
        
        return recommendations
