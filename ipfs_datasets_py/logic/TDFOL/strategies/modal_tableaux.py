"""
Modal tableaux strategy for TDFOL theorem proving.

This module implements modal tableaux proof strategy for modal formulas
(deontic, temporal, epistemic). Uses modal logic systems K, T, D, S4, S5.
"""

import logging
import time
from typing import Optional, Callable

from .base import ProverStrategy, StrategyType, ProofStep
from ..tdfol_core import (
    Formula,
    TDFOLKnowledgeBase,
    DeonticFormula,
    TemporalFormula,
    BinaryTemporalFormula,
    UnaryFormula,
    BinaryFormula,
    QuantifiedFormula,
)
from ..tdfol_prover import ProofResult, ProofStatus

logger = logging.getLogger(__name__)


class ModalTableauxStrategy(ProverStrategy):
    """
    Modal tableaux proof strategy for modal logic.
    
    This strategy uses modal tableaux methods to prove formulas containing
    modal operators (deontic, temporal, epistemic). It supports multiple
    modal logic systems:
    
    - K: Basic modal logic (minimal)
    - T: Reflexive (□φ → φ)
    - D: Serial (used for deontic logic)
    - S4: Reflexive + Transitive
    - S5: Equivalence relation (reflexive + symmetric + transitive)
    
    The strategy automatically selects the appropriate modal logic system
    based on the operators present in the formula.
    
    Characteristics:
    - Best for: Modal formulas with □, ◊, O, P, F operators
    - Completeness: Complete for respective modal logics
    - Performance: Moderate (tableaux construction can be expensive)
    - Priority: 80 (higher than general strategies for modal formulas)
    
    Example:
        >>> from ipfs_datasets_py.logic.TDFOL import TDFOLKnowledgeBase, DeonticFormula
        >>> strategy = ModalTableauxStrategy()
        >>> kb = TDFOLKnowledgeBase()
        >>> formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        >>> result = strategy.prove(formula, kb, timeout_ms=5000)
    """
    
    def __init__(self):
        """Initialize modal tableaux strategy."""
        super().__init__("Modal Tableaux", StrategyType.MODAL_TABLEAUX)
    
    def can_handle(self, formula: Formula, kb: TDFOLKnowledgeBase) -> bool:
        """
        Check if this strategy can handle the formula.
        
        Modal tableaux can handle formulas containing modal operators
        (deontic, temporal, epistemic).
        
        Args:
            formula: Formula to check
            kb: Knowledge base (not used for this check)
        
        Returns:
            True if formula contains modal operators
        """
        return self._is_modal_formula(formula)
    
    def prove(
        self,
        formula: Formula,
        kb: TDFOLKnowledgeBase,
        timeout_ms: int = 5000
    ) -> ProofResult:
        """
        Prove formula using modal tableaux method.
        
        Uses ShadowProver bridge if available, otherwise attempts
        simplified modal reasoning.
        
        Args:
            formula: Modal formula to prove
            kb: Knowledge base with axioms
            timeout_ms: Timeout in milliseconds
        
        Returns:
            ProofResult with status and proof steps
        """
        start_time = time.time()
        
        try:
            # Try ShadowProver bridge first (more powerful)
            result = self._prove_with_shadowprover(formula, timeout_ms, start_time)
            if result.status != ProofStatus.UNKNOWN:
                return result
            
            # Fallback to basic modal reasoning
            logger.debug("ShadowProver unavailable, using basic modal reasoning")
            return self._prove_basic_modal(formula, kb, timeout_ms, start_time)
            
        except Exception as e:
            logger.error(f"Modal tableaux proving failed: {e}", exc_info=True)
            return ProofResult(
                status=ProofStatus.ERROR,
                formula=formula,
                time_ms=(time.time() - start_time) * 1000,
                method=self.name,
                message=f"Error in modal tableaux proving: {e}"
            )
    
    def _prove_with_shadowprover(
        self,
        formula: Formula,
        timeout_ms: int,
        start_time: float
    ) -> ProofResult:
        """Prove using ShadowProver bridge."""
        try:
            from ..integration.tdfol_shadowprover_bridge import (
                TDFOLShadowProverBridge, ModalLogicType
            )
            
            bridge = TDFOLShadowProverBridge()
            
            if not bridge.available:
                logger.debug("ShadowProver bridge not available")
                return ProofResult(
                    status=ProofStatus.UNKNOWN,
                    formula=formula,
                    time_ms=(time.time() - start_time) * 1000,
                    method=self.name,
                    message="ShadowProver not available"
                )
            
            # Select modal logic system
            logic_type = self._select_modal_logic_type(formula)
            logger.debug(f"Using modal logic system: {logic_type.value}")
            
            # Prove via ShadowProver
            result = bridge.prove_with_shadowprover(formula, logic_type, timeout_ms)
            result.time_ms = (time.time() - start_time) * 1000
            
            if result.is_proved():
                logger.info(f"Modal tableaux proof successful using {logic_type.value}")
            else:
                logger.debug(f"Modal tableaux proof failed: {result.message}")
            
            return result
            
        except ImportError:
            logger.debug("ShadowProver bridge module not available")
            return ProofResult(
                status=ProofStatus.UNKNOWN,
                formula=formula,
                time_ms=(time.time() - start_time) * 1000,
                method=self.name,
                message="ShadowProver bridge not available"
            )
    
    def _prove_basic_modal(
        self,
        formula: Formula,
        kb: TDFOLKnowledgeBase,
        timeout_ms: int,
        start_time: float
    ) -> ProofResult:
        """Basic modal reasoning without ShadowProver."""
        # Check if formula is in KB
        if formula in kb.axioms or formula in kb.theorems:
            return ProofResult(
                status=ProofStatus.PROVED,
                formula=formula,
                proof_steps=[ProofStep(
                    formula=formula,
                    justification="Found in knowledge base"
                )],
                time_ms=(time.time() - start_time) * 1000,
                method=self.name
            )
        
        # Basic modal reasoning: Cannot prove without advanced tableaux
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=formula,
            time_ms=(time.time() - start_time) * 1000,
            method=self.name,
            message="Advanced modal tableaux not available"
        )
    
    def _is_modal_formula(self, formula: Formula) -> bool:
        """Check if formula contains modal operators."""
        if isinstance(formula, (DeonticFormula, TemporalFormula, BinaryTemporalFormula)):
            return True
        if isinstance(formula, BinaryFormula):
            return self._is_modal_formula(formula.left) or self._is_modal_formula(formula.right)
        if isinstance(formula, UnaryFormula):
            return self._is_modal_formula(formula.formula)
        if isinstance(formula, QuantifiedFormula):
            return self._is_modal_formula(formula.formula)
        return False
    
    def _select_modal_logic_type(self, formula: Formula) -> 'ModalLogicType':
        """
        Select appropriate modal logic system for formula.
        
        Selection logic:
        - Deontic operators (O, P, F) → D logic (serial accessibility)
        - Knowledge/belief → S5 (equivalence relation)
        - Temporal with nesting → S4 (reflexive + transitive)
        - Basic modal → K (minimal modal logic)
        
        Args:
            formula: Formula to analyze
        
        Returns:
            Most appropriate modal logic type
        """
        from ..integration.tdfol_shadowprover_bridge import ModalLogicType
        
        # Check for deontic operators
        if self._has_deontic_operators(formula):
            logger.debug("Deontic operators detected, using D logic")
            return ModalLogicType.D
        
        # Check for temporal operators with nesting
        if self._has_nested_temporal(formula):
            logger.debug("Nested temporal operators detected, using S4 logic")
            return ModalLogicType.S4
        
        # Check for simple temporal
        if self._has_temporal_operators(formula):
            logger.debug("Temporal operators detected, using S4 logic")
            return ModalLogicType.S4
        
        # Default to basic modal logic K
        logger.debug("Using basic modal logic K")
        return ModalLogicType.K
    
    def _traverse_formula(
        self,
        formula: Formula,
        predicate: Callable[[Formula], bool],
        depth: int = 0,
        track_depth: bool = False
    ) -> bool:
        """
        Traverse formula tree with predicate.
        
        Args:
            formula: Formula to traverse
            predicate: Function returning True if condition met
            depth: Current recursion depth
            track_depth: If True, track depth for matching formulas
        
        Returns:
            True if predicate returns True for any node
        """
        # Check predicate on current formula
        predicate_match = predicate(formula)
        
        # Track depth if needed
        new_depth = depth + 1 if (track_depth and predicate_match) else depth
        
        # Check depth threshold for nesting
        if track_depth and predicate_match and new_depth >= 2:
            return True
        
        # Non-depth-tracking returns immediately
        if not track_depth and predicate_match:
            return True
        
        # Traverse children
        if isinstance(formula, UnaryFormula):
            return self._traverse_formula(formula.formula, predicate, new_depth, track_depth)
        elif isinstance(formula, (BinaryFormula, BinaryTemporalFormula)):
            return (
                self._traverse_formula(formula.left, predicate, new_depth, track_depth) or
                self._traverse_formula(formula.right, predicate, new_depth, track_depth)
            )
        elif isinstance(formula, QuantifiedFormula):
            return self._traverse_formula(formula.formula, predicate, new_depth, track_depth)
        elif isinstance(formula, TemporalFormula):
            return self._traverse_formula(formula.formula, predicate, new_depth, track_depth)
        elif isinstance(formula, DeonticFormula):
            return self._traverse_formula(formula.formula, predicate, new_depth, track_depth)
        
        return False
    
    def _has_deontic_operators(self, formula: Formula) -> bool:
        """Check if formula contains deontic operators."""
        return self._traverse_formula(formula, lambda f: isinstance(f, DeonticFormula))
    
    def _has_temporal_operators(self, formula: Formula) -> bool:
        """Check if formula contains temporal operators."""
        return self._traverse_formula(
            formula,
            lambda f: isinstance(f, (TemporalFormula, BinaryTemporalFormula))
        )
    
    def _has_nested_temporal(self, formula: Formula) -> bool:
        """Check if formula has nested temporal operators (depth >= 2)."""
        return self._traverse_formula(
            formula,
            lambda f: isinstance(f, (TemporalFormula, BinaryTemporalFormula)),
            track_depth=True
        )
    
    def get_priority(self) -> int:
        """
        Get strategy priority.
        
        Modal tableaux has priority 80 (very high) for modal formulas,
        as it's specifically designed for them.
        
        Returns:
            Priority value of 80
        """
        return 80  # Very high priority for modal formulas
    
    def estimate_cost(self, formula: Formula, kb: TDFOLKnowledgeBase) -> float:
        """
        Estimate computational cost.
        
        Modal tableaux can be expensive due to branch expansion.
        Cost depends on formula complexity and nesting depth.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base
        
        Returns:
            Estimated cost (higher = more expensive)
        """
        # Base cost
        cost = 2.0  # Higher than forward chaining
        
        # Increase cost for nested modalities
        if self._has_nested_temporal(formula):
            cost *= 2.0
        
        # Increase cost for mixed operators
        if self._has_deontic_operators(formula) and self._has_temporal_operators(formula):
            cost *= 1.5
        
        return cost
