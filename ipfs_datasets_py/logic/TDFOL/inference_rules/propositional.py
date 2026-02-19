"""
TDFOL Propositional Inference Rules

This module implements 13 basic propositional logic inference rules for TDFOL:
- Modus Ponens, Modus Tollens
- Disjunctive Syllogism, Hypothetical Syllogism
- Conjunction Introduction/Elimination
- Disjunction Introduction
- Double Negation (Introduction/Elimination)
- Contraposition
- De Morgan's Laws (AND/OR)

These rules form the foundation for all higher-level logical reasoning.

Author: TDFOL Team
Date: 2026-02-19
Phase: 2 (Architecture Improvements)
Task: 2.1 (Split Inference Rules Monolith)
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .base import TDFOLInferenceRule
from ..tdfol_core import (
    BinaryFormula,
    Formula,
    LogicOperator,
    Predicate,
    UnaryFormula,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Propositional Logic Rules (13 rules, ~360 LOC)
# ============================================================================


class ModusPonensRule(TDFOLInferenceRule):
    """Modus Ponens: φ, φ → ψ ⊢ ψ"""
    
    def __init__(self):
        super().__init__(
            "ModusPonens",
            "From φ and φ → ψ, infer ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # Check if second formula is implication with first as antecedent
        if not isinstance(formulas[1], BinaryFormula):
            return False
        
        return (formulas[1].operator == LogicOperator.IMPLIES and
                formulas[1].left == formulas[0])
    
    def apply(self, *formulas: Formula) -> Formula:
        # Return consequent of implication
        return formulas[1].right


class ModusTollensRule(TDFOLInferenceRule):
    """Modus Tollens: φ → ψ, ¬ψ ⊢ ¬φ"""
    
    def __init__(self):
        super().__init__(
            "ModusTollens",
            "From φ → ψ and ¬ψ, infer ¬φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be implication
        if not isinstance(formulas[0], BinaryFormula):
            return False
        if formulas[0].operator != LogicOperator.IMPLIES:
            return False
        
        # Second should be negation of consequent
        if not isinstance(formulas[1], UnaryFormula):
            return False
        
        return (formulas[1].operator == LogicOperator.NOT and
                formulas[1].formula == formulas[0].right)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Return negation of antecedent
        return UnaryFormula(LogicOperator.NOT, formulas[0].left)


class DisjunctiveSyllogismRule(TDFOLInferenceRule):
    """Disjunctive Syllogism: φ ∨ ψ, ¬φ ⊢ ψ"""
    
    def __init__(self):
        super().__init__(
            "DisjunctiveSyllogism",
            "From φ ∨ ψ and ¬φ, infer ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be disjunction
        if not isinstance(formulas[0], BinaryFormula):
            return False
        if formulas[0].operator != LogicOperator.OR:
            return False
        
        # Second should be negation of left disjunct
        if not isinstance(formulas[1], UnaryFormula):
            return False
        
        return (formulas[1].operator == LogicOperator.NOT and
                formulas[1].formula == formulas[0].left)
    
    def apply(self, *formulas: Formula) -> Formula:
        return formulas[0].right


class HypotheticalSyllogismRule(TDFOLInferenceRule):
    """Hypothetical Syllogism: φ → ψ, ψ → χ ⊢ φ → χ"""
    
    def __init__(self):
        super().__init__(
            "HypotheticalSyllogism",
            "From φ → ψ and ψ → χ, infer φ → χ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # Both should be implications
        if not all(isinstance(f, BinaryFormula) for f in formulas):
            return False
        
        if not all(f.operator == LogicOperator.IMPLIES for f in formulas):
            return False
        
        # Consequent of first should match antecedent of second
        return formulas[0].right == formulas[1].left
    
    def apply(self, *formulas: Formula) -> Formula:
        return BinaryFormula(
            LogicOperator.IMPLIES,
            formulas[0].left,
            formulas[1].right
        )


class ConjunctionIntroductionRule(TDFOLInferenceRule):
    """Conjunction Introduction: φ, ψ ⊢ φ ∧ ψ"""
    
    def __init__(self):
        super().__init__(
            "ConjunctionIntroduction",
            "From φ and ψ, infer φ ∧ ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) == 2
    
    def apply(self, *formulas: Formula) -> Formula:
        return BinaryFormula(LogicOperator.AND, formulas[0], formulas[1])


class ConjunctionEliminationLeftRule(TDFOLInferenceRule):
    """Conjunction Elimination (Left): φ ∧ ψ ⊢ φ"""
    
    def __init__(self):
        super().__init__(
            "ConjunctionEliminationLeft",
            "From φ ∧ ψ, infer φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], BinaryFormula) and
                formulas[0].operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        return formulas[0].left


class ConjunctionEliminationRightRule(TDFOLInferenceRule):
    """Conjunction Elimination (Right): φ ∧ ψ ⊢ ψ"""
    
    def __init__(self):
        super().__init__(
            "ConjunctionEliminationRight",
            "From φ ∧ ψ, infer ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], BinaryFormula) and
                formulas[0].operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        return formulas[0].right


class DisjunctionIntroductionLeftRule(TDFOLInferenceRule):
    """Disjunction Introduction (Left): φ ⊢ φ ∨ ψ"""
    
    def __init__(self):
        super().__init__(
            "DisjunctionIntroductionLeft",
            "From φ, infer φ ∨ ψ for any ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) >= 1
    
    def apply(self, *formulas: Formula) -> Formula:
        # Add arbitrary second disjunct if not provided
        if len(formulas) == 1:
            # Create a fresh predicate for arbitrary ψ
            psi = Predicate("_arbitrary", ())
            return BinaryFormula(LogicOperator.OR, formulas[0], psi)
        return BinaryFormula(LogicOperator.OR, formulas[0], formulas[1])


class DoubleNegationEliminationRule(TDFOLInferenceRule):
    """Double Negation Elimination: ¬¬φ ⊢ φ"""
    
    def __init__(self):
        super().__init__(
            "DoubleNegationElimination",
            "From ¬¬φ, infer φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], UnaryFormula):
            return False
        
        if formulas[0].operator != LogicOperator.NOT:
            return False
        
        return (isinstance(formulas[0].formula, UnaryFormula) and
                formulas[0].formula.operator == LogicOperator.NOT)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Remove both negations
        return formulas[0].formula.formula


class DoubleNegationIntroductionRule(TDFOLInferenceRule):
    """Double Negation Introduction: φ ⊢ ¬¬φ"""
    
    def __init__(self):
        super().__init__(
            "DoubleNegationIntroduction",
            "From φ, infer ¬¬φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) == 1
    
    def apply(self, *formulas: Formula) -> Formula:
        negation = UnaryFormula(LogicOperator.NOT, formulas[0])
        return UnaryFormula(LogicOperator.NOT, negation)


class ContrapositionRule(TDFOLInferenceRule):
    """Contraposition: φ → ψ ⊢ ¬ψ → ¬φ"""
    
    def __init__(self):
        super().__init__(
            "Contraposition",
            "From φ → ψ, infer ¬ψ → ¬φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], BinaryFormula) and
                formulas[0].operator == LogicOperator.IMPLIES)
    
    def apply(self, *formulas: Formula) -> Formula:
        phi = formulas[0].left
        psi = formulas[0].right
        
        not_psi = UnaryFormula(LogicOperator.NOT, psi)
        not_phi = UnaryFormula(LogicOperator.NOT, phi)
        
        return BinaryFormula(LogicOperator.IMPLIES, not_psi, not_phi)


class DeMorganAndRule(TDFOLInferenceRule):
    """De Morgan (AND): ¬(φ ∧ ψ) ⊢ ¬φ ∨ ¬ψ"""
    
    def __init__(self):
        super().__init__(
            "DeMorganAnd",
            "From ¬(φ ∧ ψ), infer ¬φ ∨ ¬ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], UnaryFormula):
            return False
        
        if formulas[0].operator != LogicOperator.NOT:
            return False
        
        return (isinstance(formulas[0].formula, BinaryFormula) and
                formulas[0].formula.operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        conjunction = formulas[0].formula
        
        not_phi = UnaryFormula(LogicOperator.NOT, conjunction.left)
        not_psi = UnaryFormula(LogicOperator.NOT, conjunction.right)
        
        return BinaryFormula(LogicOperator.OR, not_phi, not_psi)


class DeMorganOrRule(TDFOLInferenceRule):
    """De Morgan (OR): ¬(φ ∨ ψ) ⊢ ¬φ ∧ ¬ψ"""
    
    def __init__(self):
        super().__init__(
            "DeMorganOr",
            "From ¬(φ ∨ ψ), infer ¬φ ∧ ¬ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], UnaryFormula):
            return False
        
        if formulas[0].operator != LogicOperator.NOT:
            return False
        
        return (isinstance(formulas[0].formula, BinaryFormula) and
                formulas[0].formula.operator == LogicOperator.OR)
    
    def apply(self, *formulas: Formula) -> Formula:
        disjunction = formulas[0].formula
        
        not_phi = UnaryFormula(LogicOperator.NOT, disjunction.left)
        not_psi = UnaryFormula(LogicOperator.NOT, disjunction.right)
        
        return BinaryFormula(LogicOperator.AND, not_phi, not_psi)


# Export all propositional rules
__all__ = [
    'ModusPonensRule',
    'ModusTollensRule',
    'DisjunctiveSyllogismRule',
    'HypotheticalSyllogismRule',
    'ConjunctionIntroductionRule',
    'ConjunctionEliminationLeftRule',
    'ConjunctionEliminationRightRule',
    'DisjunctionIntroductionLeftRule',
    'DoubleNegationEliminationRule',
    'DoubleNegationIntroductionRule',
    'ContrapositionRule',
    'DeMorganAndRule',
    'DeMorganOrRule',
]
