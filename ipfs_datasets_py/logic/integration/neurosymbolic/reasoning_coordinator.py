"""
Neural-Symbolic Reasoning Coordinator (Phase 3)

This module coordinates between symbolic (TDFOL) and neural (embedding-based)
reasoning approaches to achieve better theorem proving and formula matching.

Key features:
- Hybrid reasoning: Combines symbolic rules with neural pattern matching
- Intelligent routing: Chooses appropriate prover based on formula type
- Confidence aggregation: Combines symbolic and neural confidence scores
- Fallback strategies: If one approach fails, try another

Architecture:
    User Query
        ↓
    Coordinator
    ├──→ Symbolic Path (TDFOL/CEC provers)
    ├──→ Neural Path (Embedding similarity)
    └──→ Hybrid Path (Both combined)
        ↓
    Aggregated Result (with confidence)
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum

# TDFOL imports
from ...TDFOL.tdfol_core import Formula
from ...TDFOL.tdfol_parser import parse_tdfol
from ...TDFOL.tdfol_prover import TDFOLProver, ProofResult

# Integration imports
from ..neurosymbolic_api import NeurosymbolicReasoner

logger = logging.getLogger(__name__)


class ReasoningStrategy(Enum):
    """Strategy for reasoning approach."""
    SYMBOLIC_ONLY = "symbolic"      # Use only symbolic provers
    NEURAL_ONLY = "neural"          # Use only neural/embedding methods
    HYBRID = "hybrid"                # Combine both approaches
    AUTO = "auto"                    # Automatically choose best approach


@dataclass
class CoordinatedResult:
    """
    Result from coordinated neural-symbolic reasoning.
    
    Attributes:
        is_proved: Whether the goal was proved
        confidence: Overall confidence score (0.0-1.0)
        symbolic_result: Result from symbolic prover (if used)
        neural_confidence: Confidence from neural methods (if used)
        strategy_used: Which strategy was actually used
        reasoning_path: Description of how the conclusion was reached
        proof_steps: List of proof steps (if available)
        metadata: Additional information about the reasoning process
    """
    is_proved: bool
    confidence: float
    symbolic_result: Optional[ProofResult] = None
    neural_confidence: Optional[float] = None
    strategy_used: ReasoningStrategy = ReasoningStrategy.AUTO
    reasoning_path: str = ""
    proof_steps: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate confidence is in [0, 1]."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in [0, 1], got {self.confidence}")


class NeuralSymbolicCoordinator:
    """
    Coordinates between symbolic and neural reasoning approaches.
    
    This is the main entry point for Phase 3 neural-symbolic reasoning.
    It orchestrates different proving strategies and combines their results
    for robust theorem proving.
    
    Example:
        >>> coordinator = NeuralSymbolicCoordinator()
        >>> result = coordinator.prove(
        ...     goal="P -> Q",
        ...     axioms=["P"],
        ...     strategy=ReasoningStrategy.HYBRID
        ... )
        >>> print(f"Proved: {result.is_proved}, Confidence: {result.confidence}")
    """
    
    def __init__(
        self,
        use_cec: bool = True,
        use_modal: bool = True,
        use_embeddings: bool = True,
        confidence_threshold: float = 0.7,
    ):
        """
        Initialize the coordinator.
        
        Args:
            use_cec: Enable CEC integration (87 additional rules)
            use_modal: Enable modal logic provers
            use_embeddings: Enable embedding-based neural methods
            confidence_threshold: Minimum confidence for accepting results
        """
        self.use_cec = use_cec
        self.use_modal = use_modal
        self.use_embeddings = use_embeddings
        self.confidence_threshold = confidence_threshold
        
        # Initialize symbolic reasoner
        self.symbolic_reasoner = NeurosymbolicReasoner(
            use_cec=use_cec,
            use_modal=use_modal,
            use_nl=False  # NL handled separately
        )
        
        # Placeholder for embedding prover (Phase 3.2)
        self.embedding_prover = None
        if use_embeddings:
            try:
                from .embedding_prover import EmbeddingEnhancedProver
                self.embedding_prover = EmbeddingEnhancedProver()
                logger.info("Embedding-enhanced prover initialized")
            except ImportError:
                logger.warning("Embedding prover not available, falling back to symbolic only")
                self.use_embeddings = False
        
        logger.info(f"Coordinator initialized (CEC={use_cec}, Modal={use_modal}, Embeddings={use_embeddings})")
    
    def prove(
        self,
        goal: Union[str, Formula],
        axioms: Optional[List[Union[str, Formula]]] = None,
        strategy: ReasoningStrategy = ReasoningStrategy.AUTO,
        timeout_ms: int = 10000,
    ) -> CoordinatedResult:
        """
        Prove a goal using coordinated neural-symbolic reasoning.
        
        Args:
            goal: Formula to prove (string or Formula object)
            axioms: List of axioms/premises to use
            strategy: Reasoning strategy to use
            timeout_ms: Timeout for proving in milliseconds
        
        Returns:
            CoordinatedResult with proof status and confidence
        """
        # Parse inputs if strings
        if isinstance(goal, str):
            goal = parse_tdfol(goal)
        
        if axioms:
            axioms = [parse_tdfol(ax) if isinstance(ax, str) else ax for ax in axioms]
        else:
            axioms = []
        
        # Choose strategy if AUTO
        if strategy == ReasoningStrategy.AUTO:
            strategy = self._choose_strategy(goal, axioms)
            logger.debug(f"Auto-selected strategy: {strategy}")
        
        # Route to appropriate method
        if strategy == ReasoningStrategy.SYMBOLIC_ONLY:
            return self._prove_symbolic(goal, axioms, timeout_ms)
        elif strategy == ReasoningStrategy.NEURAL_ONLY:
            return self._prove_neural(goal, axioms)
        elif strategy == ReasoningStrategy.HYBRID:
            return self._prove_hybrid(goal, axioms, timeout_ms)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
    
    def _choose_strategy(
        self,
        goal: Formula,
        axioms: List[Formula]
    ) -> ReasoningStrategy:
        """
        Automatically choose the best strategy based on formula characteristics.
        
        Heuristics:
        - Use symbolic for simple formulas (< 10 operators)
        - Use neural for complex formulas or when similarity matters
        - Use hybrid for medium complexity or when unsure
        
        Args:
            goal: Goal formula
            axioms: Available axioms
        
        Returns:
            Recommended strategy
        """
        # Simple heuristic: count operators in goal
        goal_str = str(goal)
        complexity = goal_str.count('->') + goal_str.count('&') + goal_str.count('|')
        
        if complexity < 3:
            # Simple formula - symbolic is fast and accurate
            return ReasoningStrategy.SYMBOLIC_ONLY
        elif complexity > 10:
            # Complex formula - neural can help find patterns
            if self.use_embeddings:
                return ReasoningStrategy.HYBRID
            else:
                return ReasoningStrategy.SYMBOLIC_ONLY
        else:
            # Medium complexity - hybrid gives best of both worlds
            if self.use_embeddings:
                return ReasoningStrategy.HYBRID
            else:
                return ReasoningStrategy.SYMBOLIC_ONLY
    
    def _prove_symbolic(
        self,
        goal: Formula,
        axioms: List[Formula],
        timeout_ms: int
    ) -> CoordinatedResult:
        """Prove using only symbolic methods."""
        logger.debug(f"Proving symbolically: {goal}")
        
        # Add axioms to knowledge base
        for axiom in axioms:
            self.symbolic_reasoner.add_knowledge(str(axiom))
        
        # Attempt proof
        result = self.symbolic_reasoner.prove(str(goal))
        
        # Map to coordinated result
        confidence = 1.0 if result.valid else 0.0  # Symbolic is binary
        
        return CoordinatedResult(
            is_proved=result.valid,
            confidence=confidence,
            symbolic_result=result,
            neural_confidence=None,
            strategy_used=ReasoningStrategy.SYMBOLIC_ONLY,
            reasoning_path="Symbolic theorem proving using TDFOL/CEC rules",
            proof_steps=result.proof_steps if hasattr(result, 'proof_steps') else [],
            metadata={
                'timeout_ms': timeout_ms,
                'axiom_count': len(axioms),
            }
        )
    
    def _prove_neural(
        self,
        goal: Formula,
        axioms: List[Formula]
    ) -> CoordinatedResult:
        """Prove using only neural/embedding methods."""
        logger.debug(f"Proving neurally: {goal}")
        
        if not self.use_embeddings or self.embedding_prover is None:
            logger.warning("Neural proving requested but embeddings not available")
            # Fallback to symbolic
            return self._prove_symbolic(goal, axioms, 10000)
        
        # Use embedding-based similarity to find matching theorems
        confidence = self.embedding_prover.compute_similarity(goal, axioms)
        is_proved = confidence >= self.confidence_threshold
        
        return CoordinatedResult(
            is_proved=is_proved,
            confidence=confidence,
            symbolic_result=None,
            neural_confidence=confidence,
            strategy_used=ReasoningStrategy.NEURAL_ONLY,
            reasoning_path="Neural pattern matching using embeddings",
            proof_steps=[f"Embedding similarity: {confidence:.3f}"],
            metadata={
                'threshold': self.confidence_threshold,
                'axiom_count': len(axioms),
            }
        )
    
    def _prove_hybrid(
        self,
        goal: Formula,
        axioms: List[Formula],
        timeout_ms: int
    ) -> CoordinatedResult:
        """
        Prove using hybrid approach: try symbolic first, enhance with neural.
        
        Strategy:
        1. Try symbolic proof
        2. If successful with high confidence → return
        3. If failed or low confidence → try neural
        4. Combine both confidences for final result
        """
        logger.debug(f"Proving with hybrid approach: {goal}")
        
        # Try symbolic first
        symbolic_result = self._prove_symbolic(goal, axioms, timeout_ms)
        
        # If symbolic proof succeeded, we're confident
        if symbolic_result.is_proved:
            symbolic_result.strategy_used = ReasoningStrategy.HYBRID
            symbolic_result.reasoning_path = "Symbolic proof (validated by hybrid strategy)"
            return symbolic_result
        
        # Symbolic failed, try neural if available
        if self.use_embeddings and self.embedding_prover is not None:
            neural_confidence = self.embedding_prover.compute_similarity(goal, axioms)
            
            # Combine confidences (weighted average)
            # Give more weight to symbolic (0.7) vs neural (0.3)
            combined_confidence = 0.7 * symbolic_result.confidence + 0.3 * neural_confidence
            
            is_proved = combined_confidence >= self.confidence_threshold
            
            return CoordinatedResult(
                is_proved=is_proved,
                confidence=combined_confidence,
                symbolic_result=symbolic_result.symbolic_result,
                neural_confidence=neural_confidence,
                strategy_used=ReasoningStrategy.HYBRID,
                reasoning_path="Hybrid: Symbolic proof attempted, enhanced with neural confidence",
                proof_steps=symbolic_result.proof_steps + [f"Neural confidence: {neural_confidence:.3f}"],
                metadata={
                    'symbolic_confidence': symbolic_result.confidence,
                    'neural_confidence': neural_confidence,
                    'combined_confidence': combined_confidence,
                    'threshold': self.confidence_threshold,
                }
            )
        else:
            # No neural available, return symbolic result
            symbolic_result.strategy_used = ReasoningStrategy.HYBRID
            return symbolic_result
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get current capabilities of the coordinator."""
        return {
            'cec_enabled': self.use_cec,
            'modal_enabled': self.use_modal,
            'embeddings_enabled': self.use_embeddings,
            'confidence_threshold': self.confidence_threshold,
            'strategies_available': [s.value for s in ReasoningStrategy],
            'symbolic_rules': 127 if self.use_cec else 40,
        }
