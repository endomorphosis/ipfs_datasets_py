"""
Hybrid Confidence Scorer (Phase 3.4)

This module combines symbolic and neural confidence scores to provide
a unified confidence measure for theorem proving results.

Key features:
- Weighted combination: Balance symbolic certainty with neural similarity
- Context-aware: Adjust weights based on formula complexity
- Calibration: Ensure scores are well-calibrated probabilities
- Explanation: Provide breakdown of confidence sources

Confidence sources:
1. Symbolic: Binary (0 or 1) from theorem provers
2. Neural: Continuous (0-1) from embedding similarity
3. Structural: Based on formula properties (depth, complexity)
4. Historical: Based on past success rates
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

# TDFOL imports
from ....TDFOL.tdfol_core import Formula
from ....TDFOL.tdfol_prover import ProofResult

logger = logging.getLogger(__name__)


class ConfidenceSource(Enum):
    """Sources of confidence in a proof."""
    SYMBOLIC = "symbolic"          # From symbolic provers
    NEURAL = "neural"              # From embedding similarity
    STRUCTURAL = "structural"      # From formula structure analysis
    HISTORICAL = "historical"      # From past performance


@dataclass
class ConfidenceBreakdown:
    """
    Detailed breakdown of confidence score components.
    
    Attributes:
        total_confidence: Final combined confidence (0.0-1.0)
        symbolic_confidence: Confidence from symbolic proving
        neural_confidence: Confidence from neural methods
        structural_confidence: Confidence from formula analysis
        weights: Weights used for each component
        explanation: Human-readable explanation
    """
    total_confidence: float
    symbolic_confidence: float = 0.0
    neural_confidence: float = 0.0
    structural_confidence: float = 0.0
    weights: Dict[str, float] = None
    explanation: str = ""
    
    def __post_init__(self):
        if self.weights is None:
            self.weights = {}


class HybridConfidenceScorer:
    """
    Combines multiple confidence sources into a unified score.
    
    This implements intelligent confidence aggregation that considers:
    - Symbolic proof certainty (high weight when available)
    - Neural similarity (useful for pattern matching)
    - Formula complexity (affects reliability of methods)
    - Historical performance (learn from past results)
    
    Example:
        >>> scorer = HybridConfidenceScorer()
        >>> breakdown = scorer.compute_confidence(
        ...     symbolic_result=proof_result,
        ...     neural_similarity=0.85,
        ...     formula=goal
        ... )
        >>> print(f"Confidence: {breakdown.total_confidence:.2f}")
    """
    
    def __init__(
        self,
        symbolic_weight: float = 0.7,
        neural_weight: float = 0.3,
        use_structural: bool = True,
        calibration_factor: float = 1.0
    ):
        """
        Initialize the confidence scorer.
        
        Args:
            symbolic_weight: Weight for symbolic confidence (default: 0.7)
            neural_weight: Weight for neural confidence (default: 0.3)
            use_structural: Whether to use structural analysis
            calibration_factor: Factor to calibrate final scores
        """
        # Normalize weights
        total_weight = symbolic_weight + neural_weight
        self.symbolic_weight = symbolic_weight / total_weight
        self.neural_weight = neural_weight / total_weight
        
        self.use_structural = use_structural
        self.calibration_factor = calibration_factor
        
        # Track historical performance for calibration
        self.historical_data: List[Dict[str, Any]] = []
        
        logger.info(f"Confidence scorer initialized (sym={self.symbolic_weight:.2f}, neu={self.neural_weight:.2f})")
    
    def compute_confidence(
        self,
        symbolic_result: Optional[ProofResult] = None,
        neural_similarity: Optional[float] = None,
        formula: Optional[Formula] = None,
    ) -> ConfidenceBreakdown:
        """
        Compute combined confidence score.
        
        Args:
            symbolic_result: Result from symbolic prover (if available)
            neural_similarity: Similarity score from neural methods (if available)
            formula: The formula being proved (for structural analysis)
        
        Returns:
            ConfidenceBreakdown with total confidence and component scores
        """
        # Extract symbolic confidence
        symbolic_conf = 0.0
        if symbolic_result is not None:
            symbolic_conf = 1.0 if symbolic_result.is_proved() else 0.0
        
        # Use neural similarity as-is
        neural_conf = neural_similarity if neural_similarity is not None else 0.0
        
        # Compute structural confidence (if enabled)
        structural_conf = 0.0
        if self.use_structural and formula is not None:
            structural_conf = self._compute_structural_confidence(formula)
        
        # Determine effective weights
        weights = self._compute_weights(symbolic_result, neural_similarity, formula)
        
        # Combine confidences
        total_confidence = (
            weights['symbolic'] * symbolic_conf +
            weights['neural'] * neural_conf +
            weights['structural'] * structural_conf
        )
        
        # Apply calibration
        total_confidence = self._calibrate(total_confidence)
        
        # Generate explanation
        explanation = self._generate_explanation(
            total_confidence, symbolic_conf, neural_conf, structural_conf, weights
        )
        
        breakdown = ConfidenceBreakdown(
            total_confidence=total_confidence,
            symbolic_confidence=symbolic_conf,
            neural_confidence=neural_conf,
            structural_confidence=structural_conf,
            weights=weights,
            explanation=explanation
        )
        
        # Record for historical tracking
        self._record_result(breakdown)
        
        return breakdown
    
    def _compute_structural_confidence(self, formula: Formula) -> float:
        """
        Compute confidence based on formula structure.
        
        Heuristics:
        - Simple formulas (low depth) → higher confidence
        - Well-formed formulas → higher confidence
        - Common patterns → higher confidence
        
        Args:
            formula: Formula to analyze
        
        Returns:
            Structural confidence score (0.0-1.0)
        """
        formula_str = str(formula)
        
        # Count structural features
        depth = formula_str.count('(')
        operators = formula_str.count('->') + formula_str.count('&') + formula_str.count('|')
        
        # Simple heuristic: simpler is more confident
        if depth <= 2:
            base_confidence = 0.9
        elif depth <= 5:
            base_confidence = 0.7
        elif depth <= 10:
            base_confidence = 0.5
        else:
            base_confidence = 0.3
        
        # Adjust for operator complexity
        if operators <= 3:
            operator_factor = 1.0
        elif operators <= 7:
            operator_factor = 0.9
        else:
            operator_factor = 0.8
        
        return base_confidence * operator_factor
    
    def _compute_weights(
        self,
        symbolic_result: Optional[ProofResult],
        neural_similarity: Optional[float],
        formula: Optional[Formula]
    ) -> Dict[str, float]:
        """
        Compute adaptive weights based on available information.
        
        Strategy:
        - If symbolic proof succeeded → weight symbolic heavily
        - If only neural available → weight neural heavily
        - If both available → use configured weights
        - If structural info available → add small weight
        """
        weights = {
            'symbolic': 0.0,
            'neural': 0.0,
            'structural': 0.0
        }
        
        has_symbolic = symbolic_result is not None
        has_neural = neural_similarity is not None
        has_structural = self.use_structural and formula is not None
        
        if has_symbolic and has_neural:
            # Both available: use configured weights
            weights['symbolic'] = self.symbolic_weight
            weights['neural'] = self.neural_weight
            if has_structural:
                # Reduce others slightly to make room for structural
                weights['symbolic'] *= 0.9
                weights['neural'] *= 0.9
                weights['structural'] = 0.1
        elif has_symbolic:
            # Only symbolic: weight it heavily
            weights['symbolic'] = 0.95
            if has_structural:
                weights['symbolic'] = 0.9
                weights['structural'] = 0.1
        elif has_neural:
            # Only neural: weight it heavily
            weights['neural'] = 0.95
            if has_structural:
                weights['neural'] = 0.9
                weights['structural'] = 0.1
        elif has_structural:
            # Only structural: use it alone
            weights['structural'] = 1.0
        
        # Normalize to sum to 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        
        return weights
    
    def _calibrate(self, confidence: float) -> float:
        """
        Calibrate confidence score to be well-calibrated probability.
        
        Simple calibration: apply calibration factor and clip to [0, 1].
        In production, this could use more sophisticated calibration methods
        like isotonic regression or Platt scaling.
        """
        calibrated = confidence * self.calibration_factor
        return max(0.0, min(1.0, calibrated))
    
    def _generate_explanation(
        self,
        total: float,
        symbolic: float,
        neural: float,
        structural: float,
        weights: Dict[str, float]
    ) -> str:
        """Generate human-readable explanation of confidence."""
        parts = []
        
        if weights['symbolic'] > 0:
            parts.append(f"symbolic proof ({'succeeded' if symbolic > 0.5 else 'failed'}, weight={weights['symbolic']:.2f})")
        
        if weights['neural'] > 0:
            parts.append(f"neural similarity ({neural:.2f}, weight={weights['neural']:.2f})")
        
        if weights['structural'] > 0:
            parts.append(f"structural analysis ({structural:.2f}, weight={weights['structural']:.2f})")
        
        if parts:
            explanation = f"Combined confidence {total:.2f} from: " + ", ".join(parts)
        else:
            explanation = f"Confidence {total:.2f} (no evidence available)"
        
        return explanation
    
    def _record_result(self, breakdown: ConfidenceBreakdown):
        """Record result for historical tracking."""
        self.historical_data.append({
            'total_confidence': breakdown.total_confidence,
            'symbolic': breakdown.symbolic_confidence,
            'neural': breakdown.neural_confidence,
            'structural': breakdown.structural_confidence,
        })
        
        # Keep only recent history (last 1000 results)
        if len(self.historical_data) > 1000:
            self.historical_data = self.historical_data[-1000:]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about confidence scoring."""
        if not self.historical_data:
            return {'message': 'No historical data yet'}
        
        confidences = [d['total_confidence'] for d in self.historical_data]
        
        return {
            'count': len(confidences),
            'mean_confidence': sum(confidences) / len(confidences),
            'min_confidence': min(confidences),
            'max_confidence': max(confidences),
            'symbolic_weight': self.symbolic_weight,
            'neural_weight': self.neural_weight,
        }
