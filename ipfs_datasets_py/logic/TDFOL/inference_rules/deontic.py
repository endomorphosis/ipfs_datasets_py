"""
Deontic Logic Inference Rules for TDFOL.

This module contains 16 Standard Deontic Logic (SDL) rules:
- Deontic axioms (K, D)
- Obligation, Permission, Prohibition operators
- Deontic distribution and equivalences
- Contrary-to-duty reasoning
"""

from __future__ import annotations

from .base import TDFOLInferenceRule
from ..tdfol_core import (
    BinaryFormula,
    DeonticFormula,
    DeonticOperator,
    Formula,
    LogicOperator,
    UnaryFormula,
)


class DeonticKAxiomRule(TDFOLInferenceRule):
    """K Axiom for Deontic Logic: O(φ → ψ) → (O(φ) → O(ψ))"""
    
    def __init__(self):
        super().__init__(
            "DeonticKAxiom",
            "Distribution axiom for O: O(φ → ψ), O(φ) ⊢ O(ψ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be O(φ → ψ)
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        if not isinstance(formulas[0].formula, BinaryFormula):
            return False
        if formulas[0].formula.operator != LogicOperator.IMPLIES:
            return False
        
        # Second should be O(φ)
        if not isinstance(formulas[1], DeonticFormula):
            return False
        if formulas[1].operator != DeonticOperator.OBLIGATION:
            return False
        
        # φ from O(φ → ψ) should match φ from O(φ)
        return formulas[0].formula.left == formulas[1].formula
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract ψ from O(φ → ψ)
        psi = formulas[0].formula.right
        
        # Return O(ψ)
        return DeonticFormula(DeonticOperator.OBLIGATION, psi)


class DeonticDAxiomRule(TDFOLInferenceRule):
    """D Axiom for Deontic Logic: O(φ) ⊢ P(φ)"""
    
    def __init__(self):
        super().__init__(
            "DeonticDAxiom",
            "D axiom: obligation implies permission"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.OBLIGATION)
    
    def apply(self, *formulas: Formula) -> Formula:
        return DeonticFormula(DeonticOperator.PERMISSION, formulas[0].formula)


class ProhibitionEquivalenceRule(TDFOLInferenceRule):
    """Prohibition Equivalence: F(φ) ⊢ O(¬φ)"""
    
    def __init__(self):
        super().__init__(
            "ProhibitionEquivalence",
            "Forbidden is equivalent to obligatory not"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PROHIBITION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # F(φ) → O(¬φ)
        negation = UnaryFormula(LogicOperator.NOT, formulas[0].formula)
        return DeonticFormula(DeonticOperator.OBLIGATION, negation)


class PermissionNegationRule(TDFOLInferenceRule):
    """Permission Negation: P(φ) ⊢ ¬O(¬φ)"""
    
    def __init__(self):
        super().__init__(
            "PermissionNegation",
            "Permission is equivalent to not obligatory not"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PERMISSION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # P(φ) → ¬O(¬φ)
        negation = UnaryFormula(LogicOperator.NOT, formulas[0].formula)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, negation)
        return UnaryFormula(LogicOperator.NOT, obligation)


class ObligationConsistencyRule(TDFOLInferenceRule):
    """Obligation Consistency: O(φ) ⊢ ¬O(¬φ)"""
    
    def __init__(self):
        super().__init__(
            "ObligationConsistency",
            "Obligations are consistent: cannot oblige contradictions"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.OBLIGATION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # O(φ) → ¬O(¬φ)
        negation = UnaryFormula(LogicOperator.NOT, formulas[0].formula)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, negation)
        return UnaryFormula(LogicOperator.NOT, obligation)


class PermissionIntroductionRule(TDFOLInferenceRule):
    """Permission Introduction: φ ⊢ P(φ)"""
    
    def __init__(self):
        super().__init__(
            "PermissionIntroduction",
            "What is true is permitted"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) == 1
    
    def apply(self, *formulas: Formula) -> Formula:
        return DeonticFormula(DeonticOperator.PERMISSION, formulas[0])


class DeonticNecessitationRule(TDFOLInferenceRule):
    """Deontic Necessitation: If ⊢ φ, then ⊢ O(φ)"""
    
    def __init__(self):
        super().__init__(
            "DeonticNecessitation",
            "If φ is a theorem, it is obligatory"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        # This rule applies to theorems/axioms
        return len(formulas) == 1
    
    def apply(self, *formulas: Formula) -> Formula:
        return DeonticFormula(DeonticOperator.OBLIGATION, formulas[0])


class ProhibitionFromObligationRule(TDFOLInferenceRule):
    """Prohibition from Obligation: O(¬φ) ⊢ F(φ)"""
    
    def __init__(self):
        super().__init__(
            "ProhibitionFromObligation",
            "Obligatory not is equivalent to forbidden"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return (isinstance(formulas[0].formula, UnaryFormula) and
                formulas[0].formula.operator == LogicOperator.NOT)
    
    def apply(self, *formulas: Formula) -> Formula:
        # O(¬φ) → F(φ)
        phi = formulas[0].formula.formula  # Remove negation
        return DeonticFormula(DeonticOperator.PROHIBITION, phi)


class ObligationWeakeningRule(TDFOLInferenceRule):
    """Obligation Weakening: O(φ ∧ ψ) ⊢ O(φ)"""
    
    def __init__(self):
        super().__init__(
            "ObligationWeakening",
            "Obligation weakening: O(φ ∧ ψ) → O(φ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return (isinstance(formulas[0].formula, BinaryFormula) and
                formulas[0].formula.operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        obligation = formulas[0]
        conjunction = obligation.formula
        
        phi = conjunction.left
        
        # Return O(φ)
        return DeonticFormula(DeonticOperator.OBLIGATION, phi)


class PermissionStrengtheningRule(TDFOLInferenceRule):
    """Permission Strengthening: P(φ) ⊢ P(φ ∨ ψ)"""
    
    def __init__(self):
        super().__init__(
            "PermissionStrengthening",
            "Permission strengthening: P(φ) → P(φ ∨ ψ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 2:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PERMISSION)
    
    def apply(self, *formulas: Formula) -> Formula:
        permission = formulas[0]
        phi = permission.formula
        psi = formulas[1] if len(formulas) > 1 else Predicate("Q", [])
        
        # Create φ ∨ ψ
        disjunction = BinaryFormula(LogicOperator.OR, phi, psi)
        
        # Return P(φ ∨ ψ)
        return DeonticFormula(DeonticOperator.PERMISSION, disjunction)


class ProhibitionContrapositionRule(TDFOLInferenceRule):
    """Prohibition Contraposition: F(φ) ↔ O(¬φ)"""
    
    def __init__(self):
        super().__init__(
            "ProhibitionContraposition",
            "Forbidden is obligatory not: F(φ) ↔ O(¬φ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PROHIBITION)
    
    def apply(self, *formulas: Formula) -> Formula:
        prohibition = formulas[0]
        phi = prohibition.formula
        
        # Create ¬φ
        not_phi = UnaryFormula(LogicOperator.NOT, phi)
        
        # Return O(¬φ)
        return DeonticFormula(DeonticOperator.OBLIGATION, not_phi)


class DeonticDistributionRule(TDFOLInferenceRule):
    """Deontic Distribution: O(φ → ψ), O(φ) ⊢ O(ψ)"""
    
    def __init__(self):
        super().__init__(
            "DeonticDistribution",
            "Deontic K: O(φ → ψ) → (O(φ) → O(ψ))"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be O(φ → ψ)
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        if not isinstance(formulas[0].formula, BinaryFormula):
            return False
        if formulas[0].formula.operator != LogicOperator.IMPLIES:
            return False
        
        # Second should be O(φ)
        if not isinstance(formulas[1], DeonticFormula):
            return False
        if formulas[1].operator != DeonticOperator.OBLIGATION:
            return False
        
        # φ should match
        return formulas[0].formula.left == formulas[1].formula
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract ψ from O(φ → ψ)
        psi = formulas[0].formula.right
        
        # Return O(ψ)
        return DeonticFormula(DeonticOperator.OBLIGATION, psi)


class PermissionProhibitionDualityRule(TDFOLInferenceRule):
    """Permission-Prohibition Duality: P(φ) ↔ ¬F(φ)"""
    
    def __init__(self):
        super().__init__(
            "PermissionProhibitionDuality",
            "Permission is not forbidden: P(φ) ↔ ¬F(φ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PERMISSION)
    
    def apply(self, *formulas: Formula) -> Formula:
        permission = formulas[0]
        phi = permission.formula
        
        # Create F(φ)
        prohibition = DeonticFormula(DeonticOperator.PROHIBITION, phi)
        
        # Return ¬F(φ)
        return UnaryFormula(LogicOperator.NOT, prohibition)


class ObligationPermissionImplicationRule(TDFOLInferenceRule):
    """Obligation-Permission: O(φ) ⊢ P(φ)"""
    
    def __init__(self):
        super().__init__(
            "ObligationPermissionImplication",
            "Obligation implies permission: O(φ) → P(φ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.OBLIGATION)
    
    def apply(self, *formulas: Formula) -> Formula:
        obligation = formulas[0]
        phi = obligation.formula
        
        # Return P(φ)
        return DeonticFormula(DeonticOperator.PERMISSION, phi)


class ContraryToDutyRule(TDFOLInferenceRule):
    """Contrary-to-Duty: O(φ), ¬φ ⊢ O(ψ) for reparation ψ"""
    
    def __init__(self):
        super().__init__(
            "ContraryToDuty",
            "Contrary-to-duty obligation: O(φ) ∧ ¬φ → O(reparation)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 3:  # Need O(φ), ¬φ, and reparation ψ
            return False
        
        # First should be O(φ)
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        # Second should be ¬φ (violation)
        if not isinstance(formulas[1], UnaryFormula):
            return False
        if formulas[1].operator != LogicOperator.NOT:
            return False
        
        # φ from O(φ) should match φ from ¬φ
        return formulas[0].formula == formulas[1].formula
    
    def apply(self, *formulas: Formula) -> Formula:
        # Reparation is third formula
        reparation = formulas[2] if len(formulas) > 2 else Predicate("Reparation", [])
        
        # Return O(reparation)
        return DeonticFormula(DeonticOperator.OBLIGATION, reparation)


class DeonticDetachmentRule(TDFOLInferenceRule):
    """Deontic Detachment: O(φ → ψ), φ ⊢ O(ψ)"""
    
    def __init__(self):
        super().__init__(
            "DeonticDetachment",
            "Deontic detachment: O(φ → ψ) ∧ φ → O(ψ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be O(φ → ψ)
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        if not isinstance(formulas[0].formula, BinaryFormula):
            return False
        if formulas[0].formula.operator != LogicOperator.IMPLIES:
            return False
        
        # φ from O(φ → ψ) should match second formula
        return formulas[0].formula.left == formulas[1]
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract ψ from O(φ → ψ)
        psi = formulas[0].formula.right
        
        # Return O(ψ)
        return DeonticFormula(DeonticOperator.OBLIGATION, psi)



# Export all rules
__all__ = [
    'DeonticKAxiomRule',
    'DeonticDAxiomRule',
    'ProhibitionEquivalenceRule',
    'PermissionNegationRule',
    'ObligationConsistencyRule',
    'PermissionIntroductionRule',
    'DeonticNecessitationRule',
    'ProhibitionFromObligationRule',
    'ObligationWeakeningRule',
    'PermissionStrengtheningRule',
    'ProhibitionContrapositionRule',
    'DeonticDistributionRule',
    'PermissionProhibitionDualityRule',
    'ObligationPermissionImplicationRule',
    'ContraryToDutyRule',
    'DeonticDetachmentRule',
]
