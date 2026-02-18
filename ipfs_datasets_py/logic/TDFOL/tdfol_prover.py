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
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from .tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    DeonticFormula,
    DeonticOperator,
    Formula,
    LogicOperator,
    Predicate,
    QuantifiedFormula,
    Quantifier,
    TemporalFormula,
    TemporalOperator,
    Term,
    TDFOLKnowledgeBase,
    UnaryFormula,
    Variable,
)

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
# Proof Status
# ============================================================================


class ProofStatus(Enum):
    """Status of a proof attempt."""
    
    PROVED = "proved"
    DISPROVED = "disproved"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class ProofResult:
    """Result of a proof attempt."""
    
    status: ProofStatus
    formula: Formula
    proof_steps: List[ProofStep] = field(default_factory=list)
    time_ms: float = 0.0
    method: str = "unknown"
    message: str = ""
    
    def is_proved(self) -> bool:
        """Check if formula was proved."""
        return self.status == ProofStatus.PROVED


@dataclass
class ProofStep:
    """Single step in a proof."""
    
    formula: Formula
    justification: str
    rule_name: Optional[str] = None
    premises: List[Formula] = field(default_factory=list)


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
    
    def __init__(self, kb: Optional[TDFOLKnowledgeBase] = None, enable_cache: bool = True):
        """
        Initialize the prover with a knowledge base.
        
        Args:
            kb: Knowledge base with axioms and theorems
            enable_cache: Whether to enable proof caching for performance
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
        
        # Import and initialize all TDFOL rules (40 rules)
        try:
            from .tdfol_inference_rules import get_all_tdfol_rules
            self.tdfol_rules = get_all_tdfol_rules()
            logger.info(f"Loaded {len(self.tdfol_rules)} TDFOL inference rules")
        except Exception as e:
            logger.warning(f"Failed to load TDFOL rules: {e}")
            self.tdfol_rules = []
        
        self.temporal_rules = [r for r in self.tdfol_rules if 'Temporal' in r.name]
        self.deontic_rules = [r for r in self.tdfol_rules if 'Deontic' in r.name or 'Permission' in r.name or 'Obligation' in r.name or 'Prohibition' in r.name]
        
        # Try to use CEC prover if available
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
        
        # Try forward chaining with TDFOL rules
        result = self._forward_chaining(goal, timeout_ms)
        if result.is_proved():
            # Cache successful proof
            if self.proof_cache is not None:
                self.proof_cache.set(goal, result, list(self.kb.axioms))
            return result
        
        # Try modal tableaux for modal formulas
        if self._is_modal_formula(goal) and _try_load_modal_tableaux():
            result = self._modal_tableaux_prove(goal, timeout_ms)
            if result.is_proved():
                # Cache successful proof
                if self.proof_cache is not None:
                    self.proof_cache.set(goal, result, list(self.kb.axioms))
                return result
        
        # Try CEC prover for compatible formulas
        if self.cec_engine:
            result = self._cec_prove(goal, timeout_ms)
            if result.is_proved():
                # Cache successful proof
                if self.proof_cache is not None:
                    self.proof_cache.set(goal, result, list(self.kb.axioms))
                return result
        
        # Could not prove
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=goal,
            time_ms=(time.time() - start_time) * 1000,
            method="exhausted",
            message="Could not prove formula with available methods"
        )
    
    def _forward_chaining(self, goal: Formula, timeout_ms: int) -> ProofResult:
        """Forward chaining with TDFOL inference rules."""
        import time
        start_time = time.time()
        
        derived = set(self.kb.axioms + self.kb.theorems)
        proof_steps = []
        
        # Iteratively apply rules until goal is derived or no progress
        max_iterations = 100
        for iteration in range(max_iterations):
            if (time.time() - start_time) * 1000 > timeout_ms:
                return ProofResult(
                    status=ProofStatus.TIMEOUT,
                    formula=goal,
                    time_ms=(time.time() - start_time) * 1000,
                    method="forward_chaining"
                )
            
            # Check if goal is derived
            if goal in derived:
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=goal,
                    proof_steps=proof_steps,
                    time_ms=(time.time() - start_time) * 1000,
                    method="forward_chaining"
                )
            
            # Apply all TDFOL rules
            new_formulas = set()
            for formula in list(derived):
                # Try each rule
                for rule in self.tdfol_rules:
                    try:
                        # Single-formula rules
                        if rule.can_apply(formula):
                            new_formula = rule.apply(formula)
                            if new_formula not in derived:
                                new_formulas.add(new_formula)
                                proof_steps.append(ProofStep(
                                    new_formula,
                                    f"Applied {rule.name}",
                                    rule.name,
                                    [formula]
                                ))
                        
                        # Two-formula rules (try with other derived formulas)
                        for formula2 in list(derived):
                            if formula == formula2:
                                continue
                            try:
                                if rule.can_apply(formula, formula2):
                                    new_formula = rule.apply(formula, formula2)
                                    if new_formula not in derived:
                                        new_formulas.add(new_formula)
                                        proof_steps.append(ProofStep(
                                            new_formula,
                                            f"Applied {rule.name}",
                                            rule.name,
                                            [formula, formula2]
                                        ))
                            except (AttributeError, TypeError, ValueError) as e:
                                # Rule application failed for this formula pair
                                logger.debug(f"Rule {rule.name} failed on formula pair: {e}")
                                continue
                    except (AttributeError, TypeError, ValueError) as e:
                        logger.debug(f"Rule {rule.name} failed: {e}")
                        continue
            
            # No progress made
            if not new_formulas:
                break
            
            derived.update(new_formulas)
        
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=goal,
            proof_steps=proof_steps,
            time_ms=(time.time() - start_time) * 1000,
            method="forward_chaining",
            message="Forward chaining exhausted without proving goal"
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
    
    def _modal_tableaux_prove(self, goal: Formula, timeout_ms: int) -> ProofResult:
        """Prove using modal tableaux method via ShadowProver bridge.
        
        This method integrates with ShadowProver to leverage specialized
        modal logic provers (K, S4, S5, D) for modal formulas.
        
        Args:
            goal: Modal formula to prove
            timeout_ms: Timeout in milliseconds
            
        Returns:
            Proof result with modal tableaux details
        """
        import time
        start_time = time.time()
        
        try:
            # Import bridge
            from ..integration.tdfol_shadowprover_bridge import (
                TDFOLShadowProverBridge, ModalLogicType
            )
            
            # Create bridge instance
            bridge = TDFOLShadowProverBridge()
            
            if not bridge.available:
                logger.debug("ShadowProver bridge not available")
                return ProofResult(
                    status=ProofStatus.UNKNOWN,
                    formula=goal,
                    time_ms=(time.time() - start_time) * 1000,
                    method="modal_tableaux",
                    message="ShadowProver not available"
                )
            
            # Select appropriate modal logic system based on operators
            logic_type = self._select_modal_logic_type(goal)
            
            logger.debug(f"Using modal logic system: {logic_type.value}")
            
            # Attempt proof via ShadowProver bridge
            result = bridge.prove_with_shadowprover(goal, logic_type, timeout_ms)
            
            # Update timing information
            result.time_ms = (time.time() - start_time) * 1000
            
            if result.is_proved():
                logger.info(f"Modal tableaux proof successful using {logic_type.value}")
            else:
                logger.debug(f"Modal tableaux proof failed: {result.message}")
            
            return result
            
        except Exception as e:
            logger.error(f"Modal tableaux proving failed: {e}", exc_info=True)
            return ProofResult(
                status=ProofStatus.ERROR,
                formula=goal,
                time_ms=(time.time() - start_time) * 1000,
                method="modal_tableaux",
                message=f"Error in modal tableaux proving: {e}"
            )
    
    def _select_modal_logic_type(self, formula: Formula) -> 'ModalLogicType':
        """Select appropriate modal logic system for formula.
        
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
        
        # Check for simple temporal (always/eventually)
        if self._has_temporal_operators(formula):
            logger.debug("Temporal operators detected, using S4 logic")
            return ModalLogicType.S4
        
        # Default to basic modal logic K
        logger.debug("Using basic modal logic K")
        return ModalLogicType.K
    
    def _has_deontic_operators(self, formula: Formula) -> bool:
        """Check if formula contains deontic operators (O, P, F).
        
        Args:
            formula: Formula to check
            
        Returns:
            True if deontic operators present
        """
        if isinstance(formula, DeonticFormula):
            return True
        if isinstance(formula, BinaryFormula):
            return self._has_deontic_operators(formula.left) or self._has_deontic_operators(formula.right)
        if isinstance(formula, BinaryTemporalFormula):
            return self._has_deontic_operators(formula.left) or self._has_deontic_operators(formula.right)
        if isinstance(formula, UnaryFormula):
            return self._has_deontic_operators(formula.formula)
        if isinstance(formula, QuantifiedFormula):
            return self._has_deontic_operators(formula.formula)
        if isinstance(formula, TemporalFormula):
            return self._has_deontic_operators(formula.formula)
        return False
    
    def _has_temporal_operators(self, formula: Formula) -> bool:
        """Check if formula contains temporal operators (□, ◊, X, U, S).
        
        Args:
            formula: Formula to check
            
        Returns:
            True if temporal operators present
        """
        if isinstance(formula, TemporalFormula):
            return True
        if isinstance(formula, BinaryTemporalFormula):
            return True
        if isinstance(formula, BinaryFormula):
            return self._has_temporal_operators(formula.left) or self._has_temporal_operators(formula.right)
        if isinstance(formula, UnaryFormula):
            return self._has_temporal_operators(formula.formula)
        if isinstance(formula, QuantifiedFormula):
            return self._has_temporal_operators(formula.formula)
        if isinstance(formula, DeonticFormula):
            return self._has_temporal_operators(formula.formula)
        return False
    
    def _has_nested_temporal(self, formula: Formula, depth: int = 0) -> bool:
        """Check if formula has nested temporal operators (depth >= 2).
        
        Args:
            formula: Formula to check
            depth: Current nesting depth
            
        Returns:
            True if nested temporal operators detected
        """
        if isinstance(formula, (TemporalFormula, BinaryTemporalFormula)):
            new_depth = depth + 1
            if new_depth >= 2:
                return True
            
            if isinstance(formula, TemporalFormula):
                return self._has_nested_temporal(formula.formula, new_depth)
            else:  # BinaryTemporalFormula
                return (self._has_nested_temporal(formula.left, new_depth) or 
                       self._has_nested_temporal(formula.right, new_depth))
        
        if isinstance(formula, BinaryFormula):
            return (self._has_nested_temporal(formula.left, depth) or 
                   self._has_nested_temporal(formula.right, depth))
        if isinstance(formula, UnaryFormula):
            return self._has_nested_temporal(formula.formula, depth)
        if isinstance(formula, QuantifiedFormula):
            return self._has_nested_temporal(formula.formula, depth)
        if isinstance(formula, DeonticFormula):
            return self._has_nested_temporal(formula.formula, depth)
        
        return False
    
    def _cec_prove(self, goal: Formula, timeout_ms: int) -> ProofResult:
        """Prove using CEC inference engine."""
        # This would convert TDFOL to DCEC and use CEC prover
        # For now, return unknown
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=goal,
            method="cec_prover",
            message="CEC prover integration not yet implemented"
        )
    
    def add_axiom(self, formula: Formula, name: Optional[str] = None) -> None:
        """Add an axiom to the knowledge base."""
        self.kb.add_axiom(formula, name)
    
    def add_theorem(self, formula: Formula, name: Optional[str] = None) -> None:
        """Add a theorem to the knowledge base."""
        self.kb.add_theorem(formula, name)
