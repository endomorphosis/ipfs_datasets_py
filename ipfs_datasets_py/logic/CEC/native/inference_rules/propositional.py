"""
Propositional logic inference rules.

This module contains basic propositional logic inference rules including:
- Modus Ponens, Modus Tollens
- Simplification, Conjunction/Disjunction rules
- DeMorgan's Laws, Distribution, etc.
"""

from typing import List
from ..dcec_core import (
    Formula,
    ConnectiveFormula,
    LogicalConnective,
)
from .base import InferenceRule


class ModusPonens(InferenceRule):
    """
    Modus Ponens: From P and P→Q, derive Q.
    
    This is one of the most fundamental inference rules in logic.
    If we know P is true, and we know that P implies Q, then we can
    conclude that Q is true.
    """
    
    def name(self) -> str:
        return "Modus Ponens"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have both P and P→Q
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                    if len(f2.formulas) == 2 and self._formulas_equal(f1, f2.formulas[0]):
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                    if len(f2.formulas) == 2 and self._formulas_equal(f1, f2.formulas[0]):
                        # We have P and P→Q, so derive Q
                        results.append(f2.formulas[1])
        return results
    
    def _formulas_equal(self, f1: Formula, f2: Formula) -> bool:
        """Simple formula equality check (can be improved)."""
        return f1.to_string() == f2.to_string()


class Simplification(InferenceRule):
    """
    Simplification: From P∧Q, derive P (and Q).
    
    If we have a conjunction, we can derive each conjunct separately.
    """
    
    def name(self) -> str:
        return "Simplification"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                # Add each conjunct
                results.extend(f.formulas)
        return results


class ConjunctionIntroduction(InferenceRule):
    """
    Conjunction Introduction: From P and Q, derive P∧Q.
    
    If we have two formulas that are both true, we can derive their conjunction.
    """
    
    def name(self) -> str:
        return "Conjunction Introduction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return len(formulas) >= 2
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        # Create conjunctions of pairs of formulas
        results: List[Formula] = []
        for i, f1 in enumerate(formulas):
            for f2 in formulas[i+1:]:
                conjunction = ConnectiveFormula(LogicalConnective.AND, [f1, f2])
                results.append(conjunction)
        return results[:10]  # Limit to avoid explosion


__all__ = [
    'ModusPonens',
    'Simplification',
    'ConjunctionIntroduction',
]
