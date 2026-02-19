"""
First-Order Logic Inference Rules for TDFOL.

This module contains 2 quantifier rules for first-order logic:
- Universal Instantiation
- Existential Generalization
"""

from __future__ import annotations

from .base import TDFOLInferenceRule
from ..tdfol_core import (
    Constant,
    Formula,
    QuantifiedFormula,
    Quantifier,
    Term,
    Variable,
)


class UniversalInstantiationRule(TDFOLInferenceRule):
    """Universal Instantiation: ∀x.φ(x) ⊢ φ(t) for any term t"""
    
    def __init__(self):
        super().__init__(
            "UniversalInstantiation",
            "From ∀x.φ(x), infer φ(t) for any term t"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        return isinstance(formulas[0], QuantifiedFormula) and formulas[0].quantifier == Quantifier.FORALL
    
    def apply(self, *formulas: Formula) -> Formula:
        quantified = formulas[0]
        
        # Use provided term or variable name as constant
        if len(formulas) > 1 and isinstance(formulas[1], Term):
            term = formulas[1]
        else:
            # Default: instantiate with constant of same name
            term = Constant(quantified.variable.name)
        
        # Substitute variable with term
        return quantified.formula.substitute(quantified.variable.name, term)


class ExistentialGeneralizationRule(TDFOLInferenceRule):
    """Existential Generalization: φ(t) ⊢ ∃x.φ(x)"""
    
    def __init__(self):
        super().__init__(
            "ExistentialGeneralization",
            "From φ(t), infer ∃x.φ(x)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) >= 1
    
    def apply(self, *formulas: Formula) -> Formula:
        formula = formulas[0]
        
        # Get a variable name (use provided or create fresh)
        if len(formulas) > 1 and isinstance(formulas[1], Variable):
            var = formulas[1]
        else:
            var = Variable("x")
        
        return QuantifiedFormula(Quantifier.EXISTS, var, formula)


# Export all rules
__all__ = [
    'UniversalInstantiationRule',
    'ExistentialGeneralizationRule',
]
