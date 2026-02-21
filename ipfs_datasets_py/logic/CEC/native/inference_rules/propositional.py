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


def _flatten_formulas(formulas: List) -> List[Formula]:
    """Flatten one level of nested lists (when apply() result is passed directly)."""
    result = []
    for f in formulas:
        if isinstance(f, list):
            result.extend(f)
        else:
            result.append(f)
    return result


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
        flat = _flatten_formulas(formulas)
        # Check if we have both P and P→Q
        for f1 in flat:
            for f2 in flat:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                    if len(f2.formulas) == 2 and f1 == f2.formulas[0]:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        flat = _flatten_formulas(formulas)
        results: List[Formula] = []
        for f1 in flat:
            for f2 in flat:
                if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                    if len(f2.formulas) == 2 and f1 == f2.formulas[0]:
                        # We have P and P→Q, so derive Q
                        results.append(f2.formulas[1])
        return results


class Simplification(InferenceRule):
    """
    Simplification: From P∧Q, derive P (and Q).
    
    If we have a conjunction, we can derive each conjunct separately.
    """
    
    def name(self) -> str:
        return "Simplification"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        flat = _flatten_formulas(formulas)
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND
            for f in flat
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        flat = _flatten_formulas(formulas)
        results: List[Formula] = []
        for f in flat:
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


class Weakening(InferenceRule):
    """Weakening: From P∧Q, derive P∨Q."""
    
    def name(self) -> str:
        return "Weakening"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                # From P∧Q derive P∨Q
                disjunction = ConnectiveFormula(LogicalConnective.OR, f.formulas)
                results.append(disjunction)
        return results


class DeMorgan(InferenceRule):
    """DeMorgan's Laws: ¬(P∧Q) ↔ (¬P∨¬Q) and ¬(P∨Q) ↔ (¬P∧¬Q)."""
    
    def name(self) -> str:
        return "DeMorgan"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, ConnectiveFormula) and inner.connective in [LogicalConnective.AND, LogicalConnective.OR]:
                        return True
            elif isinstance(f, ConnectiveFormula) and f.connective in [LogicalConnective.AND, LogicalConnective.OR]:
                # Check if all sub-formulas are negations
                if all(isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.NOT for sub in f.formulas):
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            # ¬(P∧Q) → (¬P∨¬Q)
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.AND:
                        negated_and_parts: List[Formula] = [ConnectiveFormula(LogicalConnective.NOT, [sub]) for sub in inner.formulas]
                        result = ConnectiveFormula(LogicalConnective.OR, negated_and_parts)
                        results.append(result)
                    # ¬(P∨Q) → (¬P∧¬Q)
                    elif isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.OR:
                        negated_or_parts: List[Formula] = [ConnectiveFormula(LogicalConnective.NOT, [sub]) for sub in inner.formulas]
                        result = ConnectiveFormula(LogicalConnective.AND, negated_or_parts)
                        results.append(result)
            # (¬P∨¬Q) → ¬(P∧Q)
            elif isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.OR:
                if all(isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.NOT for sub in f.formulas):
                    inner_parts = [sub.formulas[0] for sub in f.formulas if isinstance(sub, ConnectiveFormula) and len(sub.formulas) == 1]
                    inner_and = ConnectiveFormula(LogicalConnective.AND, inner_parts)
                    result = ConnectiveFormula(LogicalConnective.NOT, [inner_and])
                    results.append(result)
            # (¬P∧¬Q) → ¬(P∨Q)
            elif isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.AND:
                if all(isinstance(sub, ConnectiveFormula) and sub.connective == LogicalConnective.NOT for sub in f.formulas):
                    inner_parts = [sub.formulas[0] for sub in f.formulas if isinstance(sub, ConnectiveFormula) and len(sub.formulas) == 1]
                    inner_or = ConnectiveFormula(LogicalConnective.OR, inner_parts)
                    result = ConnectiveFormula(LogicalConnective.NOT, [inner_or])
                    results.append(result)
        return results


class DoubleNegation(InferenceRule):
    """Double Negation: ¬¬P ↔ P."""
    
    def name(self) -> str:
        return "Double Negation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.NOT:
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) == 1:
                    inner = f.formulas[0]
                    if isinstance(inner, ConnectiveFormula) and inner.connective == LogicalConnective.NOT:
                        if len(inner.formulas) == 1:
                            # ¬¬P → P
                            results.append(inner.formulas[0])
        return results


class DisjunctiveSyllogism(InferenceRule):
    """Disjunctive Syllogism: From ¬P and P∨Q, derive Q."""
    
    def name(self) -> str:
        return "Disjunctive Syllogism"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have ¬P and P∨Q for some P, Q
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.NOT:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.OR:
                        if len(f1.formulas) == 1 and len(f2.formulas) >= 2:
                            negated = f1.formulas[0]
                            for disjunct in f2.formulas:
                                if negated == disjunct:
                                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.NOT:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.OR:
                        if len(f1.formulas) == 1:
                            negated = f1.formulas[0]
                            # Find the negated formula in the disjunction
                            for i, disjunct in enumerate(f2.formulas):
                                if negated == disjunct:
                                    # Derive the other disjuncts
                                    remaining = [f2.formulas[j] for j in range(len(f2.formulas)) if j != i]
                                    if len(remaining) == 1:
                                        results.append(remaining[0])
                                    elif len(remaining) > 1:
                                        results.append(ConnectiveFormula(LogicalConnective.OR, remaining))
        return results


class Contraposition(InferenceRule):
    """Contraposition: P→Q is equivalent to ¬Q→¬P."""
    
    def name(self) -> str:
        return "Contraposition"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # P→Q becomes ¬Q→¬P
                    not_q = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[1]])
                    not_p = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[0]])
                    result = ConnectiveFormula(LogicalConnective.IMPLIES, [not_q, not_p])
                    results.append(result)
        return results


class HypotheticalSyllogism(InferenceRule):
    """Hypothetical Syllogism: From (P→Q) and (Q→R), derive (P→R)."""
    
    def name(self) -> str:
        return "Hypothetical Syllogism"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check if we have two implications where consequent of first matches antecedent of second
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            if f1.formulas[1] == f2.formulas[0]:
                                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f1, ConnectiveFormula) and f1.connective == LogicalConnective.IMPLIES:
                    if isinstance(f2, ConnectiveFormula) and f2.connective == LogicalConnective.IMPLIES:
                        if len(f1.formulas) == 2 and len(f2.formulas) == 2:
                            if f1.formulas[1] == f2.formulas[0]:
                                # (P→Q) and (Q→R) gives (P→R)
                                result = ConnectiveFormula(LogicalConnective.IMPLIES, [f1.formulas[0], f2.formulas[1]])
                                results.append(result)
        return results


class ImplicationElimination(InferenceRule):
    """Implication Elimination: P→Q is equivalent to ¬P∨Q."""
    
    def name(self) -> str:
        return "Implication Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.IMPLIES:
                if len(f.formulas) == 2:
                    # P→Q becomes ¬P∨Q
                    not_p = ConnectiveFormula(LogicalConnective.NOT, [f.formulas[0]])
                    q = f.formulas[1]
                    result = ConnectiveFormula(LogicalConnective.OR, [not_p, q])
                    results.append(result)
        return results


__all__ = [
    'ModusPonens',
    'Simplification',
    'ConjunctionIntroduction',
    'Weakening',
    'DeMorgan',
    'DoubleNegation',
    'DisjunctiveSyllogism',
    'Contraposition',
    'HypotheticalSyllogism',
    'ImplicationElimination',
]
