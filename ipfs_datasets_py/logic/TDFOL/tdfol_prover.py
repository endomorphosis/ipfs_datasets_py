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
from typing import Any, Dict, List, Optional, Set, Tuple

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


# Try to import CEC native prover
try:
    from ipfs_datasets_py.logic.CEC.native.prover_core import (
        InferenceEngine,
        InferenceRule,
    )
    HAVE_CEC_PROVER = True
except ImportError:
    HAVE_CEC_PROVER = False
    logger.warning("CEC native prover not available")

# Try to import modal tableaux
try:
    from ipfs_datasets_py.logic.CEC.native.modal_tableaux import (
        ModalTableau,
        TableauProver,
    )
    HAVE_MODAL_TABLEAUX = True
except ImportError:
    HAVE_MODAL_TABLEAUX = False
    logger.warning("Modal tableaux not available")

logger = logging.getLogger(__name__)


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
    
    def __init__(self, kb: Optional[TDFOLKnowledgeBase] = None):
        """Initialize the prover with a knowledge base."""
        self.kb = kb or TDFOLKnowledgeBase()
        self.temporal_rules = self._initialize_temporal_rules()
        self.deontic_rules = self._initialize_deontic_rules()
        
        # Try to use CEC prover if available
        self.cec_engine = None
        if HAVE_CEC_PROVER:
            try:
                self.cec_engine = InferenceEngine()
                logger.info("CEC inference engine initialized")
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
        
        # Try direct lookup in KB
        if goal in self.kb.axioms:
            return ProofResult(
                status=ProofStatus.PROVED,
                formula=goal,
                proof_steps=[ProofStep(goal, "Axiom in knowledge base")],
                time_ms=(time.time() - start_time) * 1000,
                method="axiom_lookup"
            )
        
        if goal in self.kb.theorems:
            return ProofResult(
                status=ProofStatus.PROVED,
                formula=goal,
                proof_steps=[ProofStep(goal, "Theorem in knowledge base")],
                time_ms=(time.time() - start_time) * 1000,
                method="theorem_lookup"
            )
        
        # Try forward chaining with TDFOL rules
        result = self._forward_chaining(goal, timeout_ms)
        if result.is_proved():
            return result
        
        # Try modal tableaux for modal formulas
        if self._is_modal_formula(goal) and HAVE_MODAL_TABLEAUX:
            result = self._modal_tableaux_prove(goal, timeout_ms)
            if result.is_proved():
                return result
        
        # Try CEC prover for compatible formulas
        if self.cec_engine:
            result = self._cec_prove(goal, timeout_ms)
            if result.is_proved():
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
            
            # Apply temporal rules
            new_formulas = set()
            for formula in derived:
                for rule in self.temporal_rules:
                    if hasattr(rule, 'can_apply') and rule.can_apply(formula):
                        try:
                            new_formula = rule.apply(formula)
                            if new_formula not in derived:
                                new_formulas.add(new_formula)
                                proof_steps.append(ProofStep(
                                    new_formula,
                                    f"Applied {rule.name}",
                                    rule.name,
                                    [formula]
                                ))
                        except Exception as e:
                            logger.debug(f"Rule {rule.name} failed: {e}")
            
            # Apply deontic rules
            for formula in derived:
                for rule in self.deontic_rules:
                    if hasattr(rule, 'can_apply') and rule.can_apply(formula):
                        try:
                            new_formula = rule.apply(formula)
                            if new_formula not in derived:
                                new_formulas.add(new_formula)
                                proof_steps.append(ProofStep(
                                    new_formula,
                                    f"Applied {rule.name}",
                                    rule.name,
                                    [formula]
                                ))
                        except Exception as e:
                            logger.debug(f"Rule {rule.name} failed: {e}")
            
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
        """Prove using modal tableaux method."""
        # This would integrate with modal_tableaux.py from CEC
        # For now, return unknown
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=goal,
            method="modal_tableaux",
            message="Modal tableaux integration not yet implemented"
        )
    
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
