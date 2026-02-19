"""
TDFOL Prover - Theorem proving for Temporal Deontic First-Order Logic

This module provides theorem proving capabilities for TDFOL formulas, integrating:
1. CEC native prover_core inference rules (87 rules)
2. TDFOL-specific temporal-deontic reasoning
3. Modal tableaux for modal logic
4. First-order unification and resolution

The prover supports:
- Forward chaining with inference rules
- Backward chaining with goal-directed search
- Modal tableaux for K, T, D, S4, S5 logics
- Temporal reasoning with LTL operators
- Deontic reasoning with SDL (Standard Deontic Logic)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING, Callable

from .tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    DeonticFormula,
    DeonticOperator,
    Formula,
    LogicOperator,
    Predicate,
    ProofResult,
    ProofStatus,
    ProofStep,
    QuantifiedFormula,
    Quantifier,
    TemporalFormula,
    TemporalOperator,
    Term,
    TDFOLKnowledgeBase,
    UnaryFormula,
    Variable,
)

# Import proving strategies
try:
    from .strategies import (
        ProverStrategy,
        ForwardChainingStrategy,
        ModalTableauxStrategy,
        CECDelegateStrategy,
        StrategySelector,
    )
    HAVE_STRATEGIES = True
except ImportError:
    HAVE_STRATEGIES = False
    ProverStrategy = None  # type: ignore
    StrategySelector = None  # type: ignore

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ..integration.tdfol_shadowprover_bridge import ModalLogicType

# Optional provers are loaded lazily to keep imports quiet/deterministic.
InferenceEngine = None  # type: ignore[assignment]
InferenceRule = None  # type: ignore[assignment]
ModalTableau = None  # type: ignore[assignment]
TableauProver = None  # type: ignore[assignment]

HAVE_CEC_PROVER = False
HAVE_MODAL_TABLEAUX = False

_CEC_IMPORT_ATTEMPTED = False
_MODAL_TABLEAUX_IMPORT_ATTEMPTED = False


def _try_load_cec_prover() -> bool:
    global _CEC_IMPORT_ATTEMPTED, HAVE_CEC_PROVER, InferenceEngine, InferenceRule
    if HAVE_CEC_PROVER:
        return True
    if _CEC_IMPORT_ATTEMPTED:
        return False
    _CEC_IMPORT_ATTEMPTED = True
    try:
        from ipfs_datasets_py.logic.CEC.native.prover_core import (  # type: ignore
            InferenceEngine as _InferenceEngine,
            InferenceRule as _InferenceRule,
        )

        InferenceEngine = _InferenceEngine
        InferenceRule = _InferenceRule
        HAVE_CEC_PROVER = True
        return True
    except (ImportError, AttributeError, ModuleNotFoundError) as e:
        logger.debug(f"CEC prover unavailable: {e}")
        HAVE_CEC_PROVER = False
        return False


def _try_load_modal_tableaux() -> bool:
    global _MODAL_TABLEAUX_IMPORT_ATTEMPTED, HAVE_MODAL_TABLEAUX, ModalTableau, TableauProver
    if HAVE_MODAL_TABLEAUX:
        return True
    if _MODAL_TABLEAUX_IMPORT_ATTEMPTED:
        return False
    _MODAL_TABLEAUX_IMPORT_ATTEMPTED = True
    try:
        from ipfs_datasets_py.logic.CEC.native.modal_tableaux import (  # type: ignore
            ModalTableau as _ModalTableau,
            TableauProver as _TableauProver,
        )

        ModalTableau = _ModalTableau
        TableauProver = _TableauProver
        HAVE_MODAL_TABLEAUX = True
        return True
    except (ImportError, AttributeError, ModuleNotFoundError) as e:
        logger.debug(f"Modal tableaux unavailable: {e}")
        HAVE_MODAL_TABLEAUX = False
        return False


# ============================================================================
# TDFOL-specific Inference Rules
# ============================================================================


class TemporalNecessitationRule:
    """Rule: If ⊢ φ, then ⊢ □φ (Necessitation for temporal logic)."""
    
    def __init__(self):
        self.name = "TemporalNecessitation"
    
    def can_apply(self, formula: Formula, kb: TDFOLKnowledgeBase) -> bool:
        """Check if formula is derivable in KB."""
        # Simplified: check if formula is an axiom or theorem
        return formula in kb.axioms or formula in kb.theorems
    
    def apply(self, formula: Formula) -> Formula:
        """Apply necessitation: φ → □φ."""
        return TemporalFormula(TemporalOperator.ALWAYS, formula)


class DeonticNecessitationRule:
    """Rule: If ⊢ φ, then ⊢ O(φ) (Necessitation for deontic logic)."""
    
    def __init__(self):
        self.name = "DeonticNecessitation"
    
    def can_apply(self, formula: Formula, kb: TDFOLKnowledgeBase) -> bool:
        """Check if formula is a tautology or derivable."""
        return formula in kb.axioms or formula in kb.theorems
    
    def apply(self, formula: Formula) -> Formula:
        """Apply necessitation: φ → O(φ)."""
        return DeonticFormula(DeonticOperator.OBLIGATION, formula)


class TemporalDistributionRule:
    """Rule: □(φ → ψ) → (□φ → □ψ) (K axiom for temporal logic)."""
    
    def __init__(self):
        self.name = "TemporalDistribution"
    
    def can_apply(self, formula: Formula) -> bool:
        """Check if formula matches pattern □(φ → ψ)."""
        if not isinstance(formula, TemporalFormula):
            return False
        if formula.operator != TemporalOperator.ALWAYS:
            return False
        return isinstance(formula.formula, BinaryFormula) and formula.formula.operator == LogicOperator.IMPLIES
    
    def apply(self, formula: TemporalFormula, always_antecedent: TemporalFormula) -> Formula:
        """Apply distribution: □(φ → ψ), □φ ⊢ □ψ."""
        # Extract φ and ψ from □(φ → ψ)
        implication = formula.formula
        if isinstance(implication, BinaryFormula):
            psi = implication.right
            return TemporalFormula(TemporalOperator.ALWAYS, psi)
        raise ValueError("Invalid formula for temporal distribution")


class DeonticDistributionRule:
    """Rule: O(φ → ψ) → (O(φ) → O(ψ)) (K axiom for deontic logic)."""
    
    def __init__(self):
        self.name = "DeonticDistribution"
    
    def can_apply(self, formula: Formula) -> bool:
        """Check if formula matches pattern O(φ → ψ)."""
        if not isinstance(formula, DeonticFormula):
            return False
        if formula.operator != DeonticOperator.OBLIGATION:
            return False
        return isinstance(formula.formula, BinaryFormula) and formula.formula.operator == LogicOperator.IMPLIES
    
    def apply(self, formula: DeonticFormula, obligation_antecedent: DeonticFormula) -> Formula:
        """Apply distribution: O(φ → ψ), O(φ) ⊢ O(ψ)."""
        # Extract φ and ψ from O(φ → ψ)
        implication = formula.formula
        if isinstance(implication, BinaryFormula):
            psi = implication.right
            return DeonticFormula(DeonticOperator.OBLIGATION, psi)
        raise ValueError("Invalid formula for deontic distribution")


class TemporalTRule:
    """Rule: □φ → φ (T axiom - truth axiom for temporal logic)."""
    
    def __init__(self):
        self.name = "TemporalTAxiom"
    
    def can_apply(self, formula: Formula) -> bool:
        """Check if formula is □φ."""
        return isinstance(formula, TemporalFormula) and formula.operator == TemporalOperator.ALWAYS
    
    def apply(self, formula: TemporalFormula) -> Formula:
        """Apply T axiom: □φ ⊢ φ."""
        return formula.formula


class DeonticDRule:
    """Rule: O(φ) → P(φ) (D axiom - obligation implies permission)."""
    
    def __init__(self):
        self.name = "DeonticDAxiom"
    
    def can_apply(self, formula: Formula) -> bool:
        """Check if formula is O(φ)."""
        return isinstance(formula, DeonticFormula) and formula.operator == DeonticOperator.OBLIGATION
    
    def apply(self, formula: DeonticFormula) -> Formula:
        """Apply D axiom: O(φ) ⊢ P(φ)."""
        return DeonticFormula(DeonticOperator.PERMISSION, formula.formula)


class TemporalEventuallyIntroduction:
    """Rule: φ → ◊φ (Introduction of eventual truth)."""
    
    def __init__(self):
        self.name = "EventuallyIntroduction"
    
    def can_apply(self, formula: Formula) -> bool:
        """Any formula can be made eventually true."""
        return True
    
    def apply(self, formula: Formula) -> Formula:
        """Apply: φ ⊢ ◊φ."""
        return TemporalFormula(TemporalOperator.EVENTUALLY, formula)


class PermissionIntroduction:
    """Rule: φ → P(φ) (Weak permission introduction)."""
    
    def __init__(self):
        self.name = "PermissionIntroduction"
    
    def can_apply(self, formula: Formula) -> bool:
        """Any true formula is permitted."""
        return True
    
    def apply(self, formula: Formula) -> Formula:
        """Apply: φ ⊢ P(φ)."""
        return DeonticFormula(DeonticOperator.PERMISSION, formula)


class ProhibitionElimination:
    """Rule: F(φ) → ¬P(φ) (Prohibition eliminates permission)."""
    
    def __init__(self):
        self.name = "ProhibitionElimination"
    
    def can_apply(self, formula: Formula) -> bool:
        """Check if formula is F(φ)."""
        return isinstance(formula, DeonticFormula) and formula.operator == DeonticOperator.PROHIBITION
    
    def apply(self, formula: DeonticFormula) -> Formula:
        """Apply: F(φ) ⊢ ¬P(φ)."""
        permission = DeonticFormula(DeonticOperator.PERMISSION, formula.formula)
        return UnaryFormula(LogicOperator.NOT, permission)


class UntilUnfoldingRule:
    """Rule: φ U ψ ↔ ψ ∨ (φ ∧ X(φ U ψ)) (Unfold until operator)."""
    
    def __init__(self):
        self.name = "UntilUnfolding"
    
    def can_apply(self, formula: Formula) -> bool:
        """Check if formula is φ U ψ."""
        return isinstance(formula, BinaryTemporalFormula) and formula.operator == TemporalOperator.UNTIL
    
    def apply(self, formula: BinaryTemporalFormula) -> Formula:
        """Apply unfolding: φ U ψ ⊢ ψ ∨ (φ ∧ X(φ U ψ))."""
        phi = formula.left
        psi = formula.right
        
        # Create X(φ U ψ)
        next_until = TemporalFormula(TemporalOperator.NEXT, formula)
        
        # Create φ ∧ X(φ U ψ)
        conjunction = BinaryFormula(LogicOperator.AND, phi, next_until)
        
        # Create ψ ∨ (φ ∧ X(φ U ψ))
        return BinaryFormula(LogicOperator.OR, psi, conjunction)


# ============================================================================
# TDFOL Theorem Prover
# ============================================================================


class TDFOLProver:
    """Theorem prover for TDFOL formulas."""
    
    def __init__(
        self,
        kb: Optional[TDFOLKnowledgeBase] = None,
        enable_cache: bool = True,
        strategy: Optional['ProverStrategy'] = None
    ):
        """
        Initialize the prover with a knowledge base.
        
        Args:
            kb: Knowledge base with axioms and theorems
            enable_cache: Whether to enable proof caching for performance
            strategy: Optional custom proving strategy. If None, uses automatic
                      strategy selection via StrategySelector.
        """
        self.kb = kb or TDFOLKnowledgeBase()
        self.enable_cache = enable_cache
        
        # Initialize proof cache if enabled
        if self.enable_cache:
            try:
                from .tdfol_proof_cache import get_global_proof_cache
                self.proof_cache = get_global_proof_cache()
                logger.info("TDFOL proof cache enabled")
            except Exception as e:
                logger.warning(f"Failed to initialize proof cache: {e}")
                self.proof_cache = None
        else:
            self.proof_cache = None
        
        # Import and initialize all TDFOL rules (40 rules) for backward compatibility
        try:
            from .inference_rules import get_all_tdfol_rules
            self.tdfol_rules = get_all_tdfol_rules()
            logger.info(f"Loaded {len(self.tdfol_rules)} TDFOL inference rules")
        except Exception as e:
            logger.warning(f"Failed to load TDFOL rules: {e}")
            self.tdfol_rules = []
        
        self.temporal_rules = [r for r in self.tdfol_rules if 'Temporal' in r.name]
        self.deontic_rules = [r for r in self.tdfol_rules if 'Deontic' in r.name or 'Permission' in r.name or 'Obligation' in r.name or 'Prohibition' in r.name]
        
        # Initialize proving strategies
        if HAVE_STRATEGIES:
            if strategy is not None:
                # Use custom strategy
                self.strategy = strategy
                self.selector = None
                logger.info(f"Using custom proving strategy: {strategy.name}")
            else:
                # Use automatic strategy selection
                try:
                    strategies = [
                        ForwardChainingStrategy(
                            rules=self.tdfol_rules,
                            max_iterations=100
                        ),
                        ModalTableauxStrategy(),
                        CECDelegateStrategy(),
                    ]
                    self.selector = StrategySelector(strategies)
                    self.strategy = None
                    logger.info("Using automatic strategy selection (StrategySelector)")
                except Exception as e:
                    logger.warning(f"Failed to initialize StrategySelector: {e}")
                    # Fallback to legacy behavior
                    self.selector = None
                    self.strategy = None
        else:
            logger.warning("Proving strategies not available, using legacy proving methods")
            self.selector = None
            self.strategy = None
        
        # Try to use CEC prover if available (for legacy path only)
        self.cec_engine = None
        if not HAVE_STRATEGIES or self.selector is None:
            if _try_load_cec_prover():
                try:
                    self.cec_engine = InferenceEngine()
                    logger.debug("CEC inference engine initialized (legacy)")
                except Exception as e:
                    logger.warning(f"Failed to initialize CEC engine: {e}")
        self.cec_engine = None
        if _try_load_cec_prover():
            try:
                self.cec_engine = InferenceEngine()
                logger.debug("CEC inference engine initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize CEC engine: {e}")
    
    def _initialize_temporal_rules(self) -> List[Any]:
        """Initialize temporal logic inference rules."""
        return [
            TemporalNecessitationRule(),
            TemporalDistributionRule(),
            TemporalTRule(),
            TemporalEventuallyIntroduction(),
            UntilUnfoldingRule(),
        ]
    
    def _initialize_deontic_rules(self) -> List[Any]:
        """Initialize deontic logic inference rules."""
        return [
            DeonticNecessitationRule(),
            DeonticDistributionRule(),
            DeonticDRule(),
            PermissionIntroduction(),
            ProhibitionElimination(),
        ]
    
    def prove(self, goal: Formula, timeout_ms: int = 5000) -> ProofResult:
        """
        Prove a formula using available methods.
        
        This method uses the strategy pattern for proving. If a custom strategy
        was provided at initialization, it uses that strategy. Otherwise, it uses
        the StrategySelector to automatically choose the best strategy based on
        the formula characteristics.
        
        Args:
            goal: Formula to prove
            timeout_ms: Timeout in milliseconds
        
        Returns:
            ProofResult with status and proof steps
        """
        import time
        start_time = time.time()
        
        # Check cache first (O(1) lookup)
        if self.proof_cache is not None:
            cached_result = self.proof_cache.get(goal, list(self.kb.axioms))
            if cached_result is not None:
                logger.debug(f"Cache hit for formula: {goal}")
                return cached_result
        
        # Try direct lookup in KB
        if goal in self.kb.axioms:
            result = ProofResult(
                status=ProofStatus.PROVED,
                formula=goal,
                proof_steps=[ProofStep(goal, "Axiom in knowledge base")],
                time_ms=(time.time() - start_time) * 1000,
                method="axiom_lookup"
            )
            # Cache the result
            if self.proof_cache is not None:
                self.proof_cache.set(goal, result, list(self.kb.axioms))
            return result
        
        if goal in self.kb.theorems:
            result = ProofResult(
                status=ProofStatus.PROVED,
                formula=goal,
                proof_steps=[ProofStep(goal, "Theorem in knowledge base")],
                time_ms=(time.time() - start_time) * 1000,
                method="theorem_lookup"
            )
            # Cache the result
            if self.proof_cache is not None:
                self.proof_cache.set(goal, result, list(self.kb.axioms))
            return result
        
        # Use strategy pattern if available
        if HAVE_STRATEGIES and (self.selector is not None or self.strategy is not None):
            # Select strategy
            if self.strategy is not None:
                # Use custom strategy
                strategy = self.strategy
                logger.debug(f"Using custom strategy: {strategy.name}")
            else:
                # Auto-select strategy
                strategy = self.selector.select_strategy(goal, self.kb)
                logger.debug(f"Auto-selected strategy: {strategy.name} (priority: {strategy.get_priority()})")
            
            # Prove using strategy
            result = strategy.prove(goal, self.kb, timeout_ms)
            
            # Cache successful proof
            if result.is_proved() and self.proof_cache is not None:
                self.proof_cache.set(goal, result, list(self.kb.axioms))
            
            return result
        
        # Fallback: strategies not available
        logger.error("Strategies not available - cannot prove formula")
        return ProofResult(
            status=ProofStatus.ERROR,
            formula=goal,
            method="error",
            message="Proving strategies not available. Please ensure strategies module is properly installed."
        )
    
    def add_axiom(self, formula: Formula, name: Optional[str] = None) -> None:
        """Add an axiom to the knowledge base."""
        self.kb.add_axiom(formula, name)
    
    def add_theorem(self, formula: Formula, name: Optional[str] = None) -> None:
        """Add a theorem to the knowledge base."""
        self.kb.add_theorem(formula, name)
