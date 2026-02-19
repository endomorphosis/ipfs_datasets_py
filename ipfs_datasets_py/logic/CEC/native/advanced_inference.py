"""
Advanced Inference Rules for DCEC (Phase 4 Weeks 2-3)

This module provides advanced inference rules for Deontic Cognitive Event Calculus,
including modal logic, temporal reasoning, and deontic logic rules.

Features:
- Modal logic rules (K, T, S4, S5 axioms)
- Temporal reasoning rules (temporal induction, frame axioms)
- Deontic reasoning rules (deontic axioms, permission/obligation)
- Combined modal-temporal-deontic rules

These rules extend the basic inference capabilities to handle the rich
modal, temporal, and deontic operators in DCEC.

Examples:
    >>> from ipfs_datasets_py.logic.CEC.native.advanced_inference import ModalKAxiom
    >>> rule = ModalKAxiom()
    >>> # Apply K axiom: □(A→B) → (□A → □B)
    >>> result = rule.apply(formulas)
"""

from typing import List, Set, Dict, Optional, Any
from dataclasses import dataclass
import logging

from .prover_core import InferenceRule
from .dcec_core import (
    Formula,
    AtomicFormula,
    ConnectiveFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula as DCECTemporalFormula,
    LogicalConnective,
    DeonticOperator,
    CognitiveOperator,
)

try:
    from beartype import beartype
except ImportError:
    from typing import TypeVar, Callable, Any as AnyType
    F = TypeVar('F', bound=Callable[..., AnyType])
    def beartype(func: F) -> F:
        return func

logger = logging.getLogger(__name__)


# =============================================================================
# Modal Logic Rules
# =============================================================================

class ModalKAxiom(InferenceRule):
    """
    Modal K Axiom (Distribution Axiom):
    From □(A→B), derive □A → □B
    
    This is the fundamental axiom of modal logic, stating that necessity
    distributes over implication.
    
    Examples:
        If □(p→q) (necessarily, if p then q),
        then □p → □q (if necessarily p, then necessarily q)
    """
    
    def name(self) -> str:
        return "Modal K Axiom"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have □(A→B) pattern."""
        for f in formulas:
            if isinstance(f, CognitiveFormula):
                # Check if operator represents necessity (Knowledge can act as necessity)
                if f.operator == CognitiveOperator.KNOWLEDGE:
                    inner = f.formula
                    if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.IMPLIES:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply K axiom: □(A→B) → (□A → □B)."""
        results: List[Formula] = []
        
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE:
                inner = f.formula
                if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.IMPLIES:
                    if len(inner.formulas) >= 2:
                        # From □(A→B), derive □A → □B
                        a = inner.formulas[0]
                        b = inner.formulas[1]
                        
                        box_a = CognitiveFormula(CognitiveOperator.KNOWLEDGE, f.agent, a)
                        box_b = CognitiveFormula(CognitiveOperator.KNOWLEDGE, f.agent, b)
                        
                        result = ConnectiveFormula(LogicalConnective.IMPLIES, [box_a, box_b])
                        results.append(result)
        
        return results


class ModalTAxiom(InferenceRule):
    """
    Modal T Axiom (Reflexivity):
    From □A, derive A
    
    This states that if something is necessarily true, then it is actually true.
    Valid in systems where the accessibility relation is reflexive.
    
    Examples:
        If K(agent, p) (agent knows p), then p (p is true)
    """
    
    def name(self) -> str:
        return "Modal T Axiom"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have □A pattern."""
        return any(isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE 
                   for f in formulas)
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply T axiom: □A → A."""
        results: List[Formula] = []
        
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE:
                # From □A, derive A
                results.append(f.formula)
        
        return results


class ModalS4Axiom(InferenceRule):
    """
    Modal S4 Axiom (Transitivity):
    From □A, derive □□A
    
    This states that if something is necessarily true, then it is necessarily
    necessarily true. Valid when accessibility relation is transitive.
    
    Examples:
        If K(agent, p), then K(agent, K(agent, p))
        (If agent knows p, then agent knows that agent knows p)
    """
    
    def name(self) -> str:
        return "Modal S4 Axiom"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have □A pattern."""
        return any(isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE
                   for f in formulas)
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply S4 axiom: □A → □□A."""
        results: List[Formula] = []
        
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE:
                # From □A, derive □□A
                nested = CognitiveFormula(CognitiveOperator.KNOWLEDGE, f.agent, f)
                results.append(nested)
        
        return results


class ModalNecassitation(InferenceRule):
    """
    Necessitation Rule:
    If A is a theorem, then □A is a theorem
    
    This rule states that theorems are necessarily true.
    Applied to formulas that have been proven.
    
    Examples:
        If p is proven, then K(agent, p) can be derived
    """
    
    def name(self) -> str:
        return "Necessitation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Always applicable to any formula."""
        return len(formulas) > 0
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply necessitation: A → □A."""
        results: List[Formula] = []
        
        # Apply to a limited number to avoid explosion
        for f in formulas[:5]:
            if not isinstance(f, CognitiveFormula):
                # Create K(system, f) - knowledge by system
                from .dcec_core import Sort
                system = Sort("System")  # Dummy agent for system-level knowledge
                necessary = CognitiveFormula(CognitiveOperator.KNOWLEDGE, system, f)
                results.append(necessary)
        
        return results


# =============================================================================
# Temporal Reasoning Rules
# =============================================================================

class TemporalInduction(InferenceRule):
    """
    Temporal Induction Rule:
    From P(0) and ∀t(P(t) → P(t+1)), derive ∀t P(t)
    
    This is the temporal analogue of mathematical induction, allowing
    reasoning about properties that hold at all time points.
    
    Simplified version: if we have a base case and inductive step,
    we can conclude the property holds generally.
    """
    
    def name(self) -> str:
        return "Temporal Induction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have base case and inductive step pattern."""
        # Simplified check - look for implication patterns
        has_implication = any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
        return has_implication and len(formulas) >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply temporal induction (simplified)."""
        results: List[Formula] = []
        
        # Look for P and (P → P') patterns
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                    if len(f2.formulas) >= 2:
                        # If we have P and P→Q, and P and Q are similar (temporal successor)
                        # we can infer Q holds generally
                        antecedent = f2.formulas[0]
                        consequent = f2.formulas[1]
                        
                        # Simple pattern match
                        if self._similar_formulas(f1, antecedent):
                            results.append(consequent)
        
        return results[:3]  # Limit results
    
    def _similar_formulas(self, f1: Formula, f2: Formula) -> bool:
        """Check if formulas are structurally similar."""
        return f1.to_string() == f2.to_string()


class FrameAxiom(InferenceRule):
    """
    Frame Axiom:
    Properties that are not affected by an action persist
    
    If P holds and action A doesn't affect P, then P holds after A.
    This helps solve the frame problem in temporal reasoning.
    
    Simplified implementation: if a property holds and there's no
    explicit contradiction, it persists.
    """
    
    def name(self) -> str:
        return "Frame Axiom"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have persistent properties."""
        return len(formulas) > 0
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply frame axiom - properties persist unless changed."""
        results: List[Formula] = []
        
        # For each atomic formula, assume it persists
        # (unless we have evidence to the contrary)
        for f in formulas:
            if isinstance(f, AtomicFormula):
                # Property persists - in a full implementation,
                # this would check for non-interference
                results.append(f)
        
        return results[:5]  # Limit to avoid duplication


# =============================================================================
# Deontic Logic Rules
# =============================================================================

class DeonticDRule(InferenceRule):
    """
    Deontic D Axiom:
    From O(A), derive ¬O(¬A)
    
    If something is obligatory, then its negation is not obligatory.
    This ensures deontic consistency.
    
    Examples:
        If O(pay_taxes) (obligatory to pay taxes),
        then ¬O(¬pay_taxes) (not obligatory to not pay taxes)
    """
    
    def name(self) -> str:
        return "Deontic D Axiom"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have O(A) pattern."""
        return any(isinstance(f, DeonticFormula) and f.operator == DeonticOperator.OBLIGATION
                   for f in formulas)
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply D axiom: O(A) → ¬O(¬A)."""
        results: List[Formula] = []
        
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator == DeonticOperator.OBLIGATION:
                # From O(A), derive ¬O(¬A)
                inner = f.formula
                
                # Create ¬A
                neg_inner = ConnectiveFormula(LogicalConnective.NOT, [inner])
                
                # Create O(¬A)
                o_neg = DeonticFormula(DeonticOperator.OBLIGATION, neg_inner, f.agent)
                
                # Create ¬O(¬A)
                result = ConnectiveFormula(LogicalConnective.NOT, [o_neg])
                results.append(result)
        
        return results


class DeonticPermissionObligation(InferenceRule):
    """
    Deontic Permission-Obligation Relation:
    P(A) ↔ ¬O(¬A)
    
    Something is permitted if and only if its negation is not obligatory.
    This is the standard duality between permission and obligation.
    
    Examples:
        P(smoke) ↔ ¬O(¬smoke)
        (Permitted to smoke iff not obligated to not smoke)
    """
    
    def name(self) -> str:
        return "Permission-Obligation Duality"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have P(A) or O(A) patterns."""
        return any(isinstance(f, DeonticFormula) and 
                   f.operator in {DeonticOperator.PERMISSION, DeonticOperator.OBLIGATION}
                   for f in formulas)
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply P(A) ↔ ¬O(¬A) duality."""
        results: List[Formula] = []
        
        for f in formulas:
            if isinstance(f, DeonticFormula):
                if f.operator == DeonticOperator.PERMISSION:
                    # From P(A), derive ¬O(¬A)
                    neg_inner = ConnectiveFormula(LogicalConnective.NOT, [f.formula])
                    o_neg = DeonticFormula(DeonticOperator.OBLIGATION, neg_inner, f.agent)
                    result = ConnectiveFormula(LogicalConnective.NOT, [o_neg])
                    results.append(result)
                    
                elif f.operator == DeonticOperator.OBLIGATION:
                    # From O(A), derive ¬P(¬A)
                    neg_inner = ConnectiveFormula(LogicalConnective.NOT, [f.formula])
                    p_neg = DeonticFormula(DeonticOperator.PERMISSION, neg_inner, f.agent)
                    result = ConnectiveFormula(LogicalConnective.NOT, [p_neg])
                    results.append(result)
        
        return results


class DeonticDistribution(InferenceRule):
    """
    Deontic Distribution:
    From O(A∧B), derive O(A) ∧ O(B)
    
    If a conjunction is obligatory, then each conjunct is obligatory.
    
    Examples:
        If O(pay_taxes ∧ file_return),
        then O(pay_taxes) ∧ O(file_return)
    """
    
    def name(self) -> str:
        return "Deontic Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have O(A∧B) pattern."""
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator == DeonticOperator.OBLIGATION:
                inner = f.formula
                if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.AND:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply distribution: O(A∧B) → O(A) ∧ O(B)."""
        results: List[Formula] = []
        
        for f in formulas:
            if isinstance(f, DeonticFormula) and f.operator == DeonticOperator.OBLIGATION:
                inner = f.formula
                if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.AND:
                    # From O(A∧B), derive O(A) and O(B)
                    obligations = []
                    for conjunct in inner.formulas:
                        o_conjunct = DeonticFormula(f.operator, conjunct, f.agent)
                        obligations.append(o_conjunct)
                    
                    # Return conjunction of obligations
                    if len(obligations) >= 2:
                        result = ConnectiveFormula(LogicalConnective.AND, obligations)
                        results.append(result)
        
        return results


# =============================================================================
# Combined Modal-Temporal-Deontic Rules
# =============================================================================

class KnowledgeObligation(InferenceRule):
    """
    Knowledge-Obligation Interaction:
    From K(agent, O(A)), derive O(K(agent, A))
    
    If an agent knows they have an obligation, then they are obligated
    to know the content. This connects epistemic and deontic modalities.
    
    Simplified rule for demonstrating modal interaction.
    """
    
    def name(self) -> str:
        return "Knowledge-Obligation Interaction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have K(O(A)) pattern."""
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE:
                inner = f.formula
                if isinstance(inner, DeonticFormula):
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply K(O(A)) → O(K(A)) (simplified)."""
        results: List[Formula] = []
        
        for f in formulas:
            if isinstance(f, CognitiveFormula) and f.operator == CognitiveOperator.KNOWLEDGE:
                inner = f.formula
                if isinstance(inner, DeonticFormula):
                    # From K(O(A)), derive O(K(A))
                    content = inner.formula
                    k_content = CognitiveFormula(CognitiveOperator.KNOWLEDGE, f.agent, content)
                    result = DeonticFormula(inner.operator, inner.agent, k_content)
                    results.append(result)
        
        return results


class TemporalObligation(InferenceRule):
    """
    Temporal-Deontic Interaction:
    From O(◇A), derive ◇O(A) (simplified)
    
    If there's an obligation for something to eventually happen,
    then eventually there will be an obligation for it.
    
    This demonstrates interaction between temporal and deontic operators.
    Simplified for demonstration purposes.
    """
    
    def name(self) -> str:
        return "Temporal-Deontic Interaction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have temporal-deontic combinations."""
        # Simplified check
        has_deontic = any(isinstance(f, DeonticFormula) for f in formulas)
        return has_deontic
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply temporal-deontic interaction rules."""
        results: List[Formula] = []
        
        # Simplified: if we have O(A), we can infer it persists temporally
        for f in formulas:
            if isinstance(f, DeonticFormula):
                # Obligations tend to persist until fulfilled
                results.append(f)
        
        return results[:3]  # Limit results


# =============================================================================
# Helper Functions
# =============================================================================

def get_all_advanced_rules() -> List[InferenceRule]:
    """
    Get all advanced inference rules.
    
    Returns:
        List of instantiated advanced inference rules
    """
    return [
        # Modal logic rules
        ModalKAxiom(),
        ModalTAxiom(),
        ModalS4Axiom(),
        ModalNecassitation(),
        
        # Temporal reasoning rules
        TemporalInduction(),
        FrameAxiom(),
        
        # Deontic logic rules
        DeonticDRule(),
        DeonticPermissionObligation(),
        DeonticDistribution(),
        
        # Combined rules
        KnowledgeObligation(),
        TemporalObligation(),
    ]


def get_modal_rules() -> List[InferenceRule]:
    """Get only modal logic rules."""
    return [
        ModalKAxiom(),
        ModalTAxiom(),
        ModalS4Axiom(),
        ModalNecassitation(),
    ]


def get_temporal_rules() -> List[InferenceRule]:
    """Get only temporal reasoning rules."""
    return [
        TemporalInduction(),
        FrameAxiom(),
    ]


def get_deontic_rules() -> List[InferenceRule]:
    """Get only deontic logic rules."""
    return [
        DeonticDRule(),
        DeonticPermissionObligation(),
        DeonticDistribution(),
    ]


def get_combined_rules() -> List[InferenceRule]:
    """Get combined modal-temporal-deontic rules."""
    return [
        KnowledgeObligation(),
        TemporalObligation(),
    ]
