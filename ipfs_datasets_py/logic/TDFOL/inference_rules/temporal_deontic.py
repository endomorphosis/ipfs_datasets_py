"""
Temporal-Deontic Logic Inference Rules for TDFOL.

This module contains 9 combined temporal-deontic rules:
- Temporal obligations and permissions
- Deontic-temporal operators (O, P, F with □, ◊, X, U)
- Future obligation persistence
- Temporal permission weakening
"""

from __future__ import annotations

from .base import TDFOLInferenceRule
from ..tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    DeonticFormula,
    DeonticOperator,
    Formula,
    LogicOperator,
    TemporalFormula,
    TemporalOperator,
)


class TemporalObligationPersistenceRule(TDFOLInferenceRule):
    """Temporal Obligation Persistence: O(□φ) ⊢ □O(φ)"""
    
    def __init__(self):
        super().__init__(
            "TemporalObligationPersistence",
            "Obligation of always implies always obligated"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.ALWAYS)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from O(□φ)
        phi = formulas[0].formula.formula
        
        # Create O(φ)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, phi)
        
        # Create □O(φ)
        return TemporalFormula(TemporalOperator.ALWAYS, obligation)


class DeonticTemporalIntroductionRule(TDFOLInferenceRule):
    """Deontic Temporal Introduction: O(φ) ⊢ O(Xφ)"""
    
    def __init__(self):
        super().__init__(
            "DeonticTemporalIntroduction",
            "Obligation persists to next time"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.OBLIGATION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from O(φ)
        phi = formulas[0].formula
        
        # Create X(φ)
        next_phi = TemporalFormula(TemporalOperator.NEXT, phi)
        
        # Create O(X(φ))
        return DeonticFormula(DeonticOperator.OBLIGATION, next_phi)


class UntilObligationRule(TDFOLInferenceRule):
    """Until Obligation: O(φ U ψ) ⊢ ◊O(ψ)"""
    
    def __init__(self):
        super().__init__(
            "UntilObligation",
            "Obligation of until implies eventual obligation of goal"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return isinstance(formulas[0].formula, BinaryTemporalFormula)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract ψ from O(φ U ψ)
        psi = formulas[0].formula.right
        
        # Create O(ψ)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, psi)
        
        # Create ◊O(ψ)
        return TemporalFormula(TemporalOperator.EVENTUALLY, obligation)


class AlwaysPermissionRule(TDFOLInferenceRule):
    """Always Permission: P(□φ) ⊢ □P(φ)"""
    
    def __init__(self):
        super().__init__(
            "AlwaysPermission",
            "Permission of always implies always permitted"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.PERMISSION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.ALWAYS)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from P(□φ)
        phi = formulas[0].formula.formula
        
        # Create P(φ)
        permission = DeonticFormula(DeonticOperator.PERMISSION, phi)
        
        # Create □P(φ)
        return TemporalFormula(TemporalOperator.ALWAYS, permission)


class EventuallyForbiddenRule(TDFOLInferenceRule):
    """Eventually Forbidden: F(◊φ) ⊢ □F(φ)"""
    
    def __init__(self):
        super().__init__(
            "EventuallyForbidden",
            "Forbidden eventually implies always forbidden"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.PROHIBITION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.EVENTUALLY)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from F(◊φ)
        phi = formulas[0].formula.formula
        
        # Create F(φ)
        prohibition = DeonticFormula(DeonticOperator.PROHIBITION, phi)
        
        # Create □F(φ)
        return TemporalFormula(TemporalOperator.ALWAYS, prohibition)


class ObligationEventuallyRule(TDFOLInferenceRule):
    """Obligation Eventually: O(◊φ) ⊢ ◊O(φ)"""
    
    def __init__(self):
        super().__init__(
            "ObligationEventually",
            "Obligation of eventually implies eventually obligated"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.EVENTUALLY)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from O(◊φ)
        phi = formulas[0].formula.formula
        
        # Create O(φ)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, phi)
        
        # Create ◊O(φ)
        return TemporalFormula(TemporalOperator.EVENTUALLY, obligation)


class PermissionTemporalWeakeningRule(TDFOLInferenceRule):
    """Permission Temporal Weakening: P(φ) ⊢ P(◊φ)"""
    
    def __init__(self):
        super().__init__(
            "PermissionTemporalWeakening",
            "Permission implies permission eventually"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PERMISSION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from P(φ)
        phi = formulas[0].formula
        
        # Create ◊φ
        eventually = TemporalFormula(TemporalOperator.EVENTUALLY, phi)
        
        # Create P(◊φ)
        return DeonticFormula(DeonticOperator.PERMISSION, eventually)


class AlwaysObligationDistributionRule(TDFOLInferenceRule):
    """Always-Obligation Distribution: □O(φ) ⊢ O(□φ)"""
    
    def __init__(self):
        super().__init__(
            "AlwaysObligationDistribution",
            "Always obligated distributes to obligated always: □O(φ) → O(□φ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        if not isinstance(formulas[0], TemporalFormula):
            return False
        if formulas[0].operator != TemporalOperator.ALWAYS:
            return False
        
        return (isinstance(formulas[0].formula, DeonticFormula) and
                formulas[0].formula.operator == DeonticOperator.OBLIGATION)
    
    def apply(self, *formulas: Formula) -> Formula:
        always_obligation = formulas[0]
        obligation = always_obligation.formula
        phi = obligation.formula
        
        # Create □φ
        always_phi = TemporalFormula(TemporalOperator.ALWAYS, phi)
        
        # Return O(□φ)
        return DeonticFormula(DeonticOperator.OBLIGATION, always_phi)


class FutureObligationPersistenceRule(TDFOLInferenceRule):
    """Future Obligation Persistence: O(Xφ) ⊢ X(O(φ))"""
    
    def __init__(self):
        super().__init__(
            "FutureObligationPersistence",
            "Future obligation persists: O(Xφ) → X(O(φ))"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.NEXT)
    
    def apply(self, *formulas: Formula) -> Formula:
        obligation = formulas[0]
        next_phi = obligation.formula
        phi = next_phi.formula
        
        # Create O(φ)
        obligation_phi = DeonticFormula(DeonticOperator.OBLIGATION, phi)
        
        # Return X(O(φ))
        return TemporalFormula(TemporalOperator.NEXT, obligation_phi)



# Export all rules
__all__ = [
    'TemporalObligationPersistenceRule',
    'DeonticTemporalIntroductionRule',
    'UntilObligationRule',
    'AlwaysPermissionRule',
    'EventuallyForbiddenRule',
    'ObligationEventuallyRule',
    'PermissionTemporalWeakeningRule',
    'AlwaysObligationDistributionRule',
    'FutureObligationPersistenceRule',
]
