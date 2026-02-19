"""
CEC delegate strategy for TDFOL theorem proving.

This module implements a strategy that delegates proving to the CEC
(Combined Event Calculus) inference engine when available.
"""

import logging
import time
from typing import Optional

from .base import ProverStrategy, StrategyType, ProofStep
from ..tdfol_core import Formula, TDFOLKnowledgeBase
from ..tdfol_prover import ProofResult, ProofStatus

logger = logging.getLogger(__name__)


# Global flags for CEC availability
_CEC_IMPORT_ATTEMPTED = False
HAVE_CEC_PROVER = False
InferenceEngine = None


def _try_load_cec_prover() -> bool:
    """Try to load CEC prover."""
    global _CEC_IMPORT_ATTEMPTED, HAVE_CEC_PROVER, InferenceEngine
    
    if HAVE_CEC_PROVER:
        return True
    if _CEC_IMPORT_ATTEMPTED:
        return False
    
    _CEC_IMPORT_ATTEMPTED = True
    try:
        from ipfs_datasets_py.logic.CEC.native.prover_core import (
            InferenceEngine as _InferenceEngine,
        )
        InferenceEngine = _InferenceEngine
        HAVE_CEC_PROVER = True
        logger.debug("CEC prover loaded successfully")
        return True
    except (ImportError, AttributeError, ModuleNotFoundError) as e:
        logger.debug(f"CEC prover unavailable: {e}")
        HAVE_CEC_PROVER = False
        return False


class CECDelegateStrategy(ProverStrategy):
    """
    Strategy that delegates proving to CEC inference engine.
    
    The Combined Event Calculus (CEC) prover provides powerful inference
    capabilities for event-based reasoning and can handle many TDFOL formulas.
    This strategy delegates to the CEC engine when available.
    
    Characteristics:
    - Best for: Formulas compatible with CEC representation
    - Completeness: Depends on CEC prover capabilities
    - Performance: Good (CEC engine is optimized)
    - Priority: 60 (medium-high, tries after specialized strategies)
    
    Example:
        >>> from ipfs_datasets_py.logic.TDFOL import TDFOLKnowledgeBase, Predicate
        >>> strategy = CECDelegateStrategy()
        >>> kb = TDFOLKnowledgeBase()
        >>> formula = Predicate("P", ())
        >>> if strategy.can_handle(formula, kb):
        ...     result = strategy.prove(formula, kb, timeout_ms=5000)
    """
    
    def __init__(self):
        """Initialize CEC delegate strategy."""
        super().__init__("CEC Delegate", StrategyType.CEC_DELEGATE)
        self.cec_engine = None
        
        # Try to initialize CEC engine
        if _try_load_cec_prover():
            try:
                self.cec_engine = InferenceEngine()
                logger.debug("CEC inference engine initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize CEC engine: {e}")
                self.cec_engine = None
    
    def can_handle(self, formula: Formula, kb: TDFOLKnowledgeBase) -> bool:
        """
        Check if this strategy can handle the formula.
        
        Can handle formula if:
        1. CEC prover is available
        2. Formula is compatible with CEC representation
        
        Args:
            formula: Formula to check
            kb: Knowledge base
        
        Returns:
            True if CEC engine available and formula compatible
        """
        # Check if CEC engine is available
        if not HAVE_CEC_PROVER or self.cec_engine is None:
            return False
        
        # For now, assume all formulas are potentially compatible
        # A more sophisticated implementation would check formula structure
        return True
    
    def prove(
        self,
        formula: Formula,
        kb: TDFOLKnowledgeBase,
        timeout_ms: int = 5000
    ) -> ProofResult:
        """
        Prove formula by delegating to CEC engine.
        
        Converts TDFOL formula to CEC representation and uses
        CEC inference engine for proving.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base with axioms
            timeout_ms: Timeout in milliseconds
        
        Returns:
            ProofResult with status and proof steps
        """
        start_time = time.time()
        
        # Check if CEC engine available
        if not HAVE_CEC_PROVER or self.cec_engine is None:
            return ProofResult(
                status=ProofStatus.UNKNOWN,
                formula=formula,
                time_ms=(time.time() - start_time) * 1000,
                method=self.name,
                message="CEC prover not available"
            )
        
        try:
            # Check if formula in KB first
            if formula in kb.axioms:
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=formula,
                    proof_steps=[ProofStep(
                        formula=formula,
                        justification="Axiom in knowledge base"
                    )],
                    time_ms=(time.time() - start_time) * 1000,
                    method=self.name
                )
            
            if formula in kb.theorems:
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=formula,
                    proof_steps=[ProofStep(
                        formula=formula,
                        justification="Theorem in knowledge base"
                    )],
                    time_ms=(time.time() - start_time) * 1000,
                    method=self.name
                )
            
            # TODO: Convert TDFOL formula to CEC format and prove
            # This requires implementing TDFOL -> DCEC conversion
            # For now, return UNKNOWN
            
            logger.debug("CEC prover integration not yet fully implemented")
            return ProofResult(
                status=ProofStatus.UNKNOWN,
                formula=formula,
                time_ms=(time.time() - start_time) * 1000,
                method=self.name,
                message="CEC prover integration in progress"
            )
            
        except Exception as e:
            logger.error(f"CEC proving failed: {e}", exc_info=True)
            return ProofResult(
                status=ProofStatus.ERROR,
                formula=formula,
                time_ms=(time.time() - start_time) * 1000,
                method=self.name,
                message=f"Error in CEC proving: {e}"
            )
    
    def get_priority(self) -> int:
        """
        Get strategy priority.
        
        CEC delegate has medium-high priority (60), tried after
        specialized strategies but before general ones.
        
        Returns:
            Priority value of 60
        """
        return 60  # Medium-high priority
    
    def estimate_cost(self, formula: Formula, kb: TDFOLKnowledgeBase) -> float:
        """
        Estimate computational cost.
        
        CEC engine is generally efficient, so cost is moderate.
        
        Args:
            formula: Formula to prove
            kb: Knowledge base
        
        Returns:
            Estimated cost (higher = more expensive)
        """
        # CEC engine is efficient, moderate cost
        return 1.5
