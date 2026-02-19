"""
Temporal Logic Inference Rules for CEC

This module contains inference rules for temporal logic operators including:
- Always (□): □P means P holds at all times
- Eventually (◊): ◊P means P holds at some time
- Until (U): P U Q means P holds until Q becomes true
- Since (S): P S Q means P has held since Q was true
- Next (○): ○P means P holds at the next time point

Author: CEC Team
Date: 2026-02-19
"""

from typing import List
from ..dcec_core import (
    Formula, TemporalFormula, ConnectiveFormula, LogicalConnective,
    TemporalOperator
)
from .base import InferenceRule


# ==============================================================================
# Always (□) Operator Rules
# ==============================================================================

class AlwaysDistribution(InferenceRule):
    """Always Distribution: □(P∧Q) ⊢ □P ∧ □Q
    
    If a conjunction holds at all times, then each conjunct holds at all times.
    """
    
    def name(self) -> str:
        return "Always Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    # □(P∧Q) → □P ∧ □Q
                    always_formulas: List[Formula] = []
                    for subformula in f.formula.formulas:
                        always_f = TemporalFormula(f.operator, subformula)
                        always_formulas.append(always_f)
                    result = ConnectiveFormula(LogicalConnective.AND, always_formulas)
                    results.append(result)
        return results


class AlwaysImplication(InferenceRule):
    """Always Implication: □P ∧ □(P→Q) ⊢ □Q
    
    If P always holds and P always implies Q, then Q always holds.
    """
    
    def name(self) -> str:
        return "Always Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for af1 in always_formulas:
            for af2 in always_formulas:
                if isinstance(af2.formula, ConnectiveFormula) and af2.formula.connective == LogicalConnective.IMPLIES:
                    if len(af2.formula.formulas) == 2:
                        if af1.formula == af2.formula.formulas[0]:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for af1 in always_formulas:
            for af2 in always_formulas:
                if isinstance(af2.formula, ConnectiveFormula) and af2.formula.connective == LogicalConnective.IMPLIES:
                    if len(af2.formula.formulas) == 2:
                        if af1.formula == af2.formula.formulas[0]:
                            # □P and □(P→Q), derive □Q
                            new_always = TemporalFormula(af1.operator, af2.formula.formulas[1])
                            results.append(new_always)
        return results


class AlwaysTransitive(InferenceRule):
    """Always Transitive: □□P ⊢ □P
    
    If it's always the case that it's always P, then it's always P.
    """
    
    def name(self) -> str:
        return "Always Transitive"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, TemporalFormula) and f.formula.operator.value == "ALWAYS":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                if isinstance(f.formula, TemporalFormula) and f.formula.operator.value == "ALWAYS":
                    # □□P → □P
                    result = TemporalFormula(f.operator, f.formula.formula)
                    results.append(result)
        return results


class AlwaysImpliesNext(InferenceRule):
    """Always Implies Next: □P ⊢ ○P
    
    If P always holds, then P holds at the next time point.
    """
    
    def name(self) -> str:
        return "Always Implies Next"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                # □P → ○P
                next_formula = TemporalFormula(TemporalOperator.NEXT, f.formula)
                results.append(next_formula)
        return results


class AlwaysInduction(InferenceRule):
    """Always Induction: P ∧ □(P→○P) ⊢ □P
    
    If P holds now and whenever P holds it will hold next, then P always holds.
    """
    
    def name(self) -> str:
        return "Always Induction"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        # Check for P and □(P→○P) pattern
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, TemporalFormula) and f2.operator.value == "ALWAYS":
                    if isinstance(f2.formula, ConnectiveFormula) and f2.formula.connective == LogicalConnective.IMPLIES:
                        if len(f2.formula.formulas) == 2:
                            antecedent = f2.formula.formulas[0]
                            consequent = f2.formula.formulas[1]
                            if f1 == antecedent:
                                if isinstance(consequent, TemporalFormula) and consequent.operator.value == "NEXT":
                                    if consequent.formula == f1:
                                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f1 in formulas:
            for f2 in formulas:
                if isinstance(f2, TemporalFormula) and f2.operator.value == "ALWAYS":
                    if isinstance(f2.formula, ConnectiveFormula) and f2.formula.connective == LogicalConnective.IMPLIES:
                        if len(f2.formula.formulas) == 2:
                            antecedent = f2.formula.formulas[0]
                            consequent = f2.formula.formulas[1]
                            if f1 == antecedent:
                                if isinstance(consequent, TemporalFormula) and consequent.operator.value == "NEXT":
                                    if consequent.formula == f1:
                                        # P and □(P→○P) → □P
                                        always_p = TemporalFormula(TemporalOperator.ALWAYS, f1)
                                        results.append(always_p)
        return results


# ==============================================================================
# Eventually (◊) Operator Rules
# ==============================================================================

class EventuallyFromAlways(InferenceRule):
    """Eventually from Always: □P ⊢ ◊P
    
    If P always holds, then P holds at some time (in particular, now).
    """
    
    def name(self) -> str:
        return "Eventually from Always"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        return any(
            isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"
            for f in formulas
        )
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS":
                # □P → ◊P
                eventually = TemporalFormula(TemporalOperator.EVENTUALLY, f.formula)
                results.append(eventually)
        return results


class EventuallyDistribution(InferenceRule):
    """Eventually Distribution: ◊(P∨Q) ⊢ ◊P ∨ ◊Q
    
    If a disjunction holds eventually, then at least one disjunct holds eventually.
    """
    
    def name(self) -> str:
        return "Eventually Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.OR:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.OR:
                    # ◊(P∨Q) → ◊P ∨ ◊Q
                    eventually_formulas: List[Formula] = []
                    for subformula in f.formula.formulas:
                        eventually_f = TemporalFormula(f.operator, subformula)
                        eventually_formulas.append(eventually_f)
                    result = ConnectiveFormula(LogicalConnective.OR, eventually_formulas)
                    results.append(result)
        return results


class EventuallyTransitive(InferenceRule):
    """Eventually Transitive: ◊◊P ⊢ ◊P
    
    If it's eventually the case that it's eventually P, then it's eventually P.
    """
    
    def name(self) -> str:
        return "Eventually Transitive"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY":
                if isinstance(f.formula, TemporalFormula) and f.formula.operator.value == "EVENTUALLY":
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY":
                if isinstance(f.formula, TemporalFormula) and f.formula.operator.value == "EVENTUALLY":
                    # ◊◊P → ◊P
                    result = TemporalFormula(f.operator, f.formula.formula)
                    results.append(result)
        return results


class EventuallyImplication(InferenceRule):
    """Eventually Implication: ◊P ∧ □(P→Q) ⊢ ◊Q
    
    If P eventually holds and P always implies Q, then Q eventually holds.
    """
    
    def name(self) -> str:
        return "Eventually Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        eventually_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY"]
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for ef in eventually_formulas:
            for af in always_formulas:
                if isinstance(af.formula, ConnectiveFormula) and af.formula.connective == LogicalConnective.IMPLIES:
                    if len(af.formula.formulas) == 2:
                        if ef.formula == af.formula.formulas[0]:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        eventually_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "EVENTUALLY"]
        always_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "ALWAYS"]
        
        for ef in eventually_formulas:
            for af in always_formulas:
                if isinstance(af.formula, ConnectiveFormula) and af.formula.connective == LogicalConnective.IMPLIES:
                    if len(af.formula.formulas) == 2:
                        if ef.formula == af.formula.formulas[0]:
                            # ◊P and □(P→Q) → ◊Q
                            new_eventually = TemporalFormula(ef.operator, af.formula.formulas[1])
                            results.append(new_eventually)
        return results


# ==============================================================================
# Next (○) Operator Rules
# ==============================================================================

class NextDistribution(InferenceRule):
    """Next Distribution: ○(P∧Q) ⊢ ○P ∧ ○Q
    
    If a conjunction holds at the next time, each conjunct holds at the next time.
    """
    
    def name(self) -> str:
        return "Next Distribution"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "NEXT":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "NEXT":
                if isinstance(f.formula, ConnectiveFormula) and f.formula.connective == LogicalConnective.AND:
                    # ○(P∧Q) → ○P ∧ ○Q
                    next_formulas: List[Formula] = []
                    for subformula in f.formula.formulas:
                        next_f = TemporalFormula(f.operator, subformula)
                        next_formulas.append(next_f)
                    result = ConnectiveFormula(LogicalConnective.AND, next_formulas)
                    results.append(result)
        return results


class NextImplication(InferenceRule):
    """Next Implication: ○P ∧ ○(P→Q) ⊢ ○Q
    
    If P holds next and P implies Q holds next, then Q holds next.
    """
    
    def name(self) -> str:
        return "Next Implication"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        next_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "NEXT"]
        
        for nf1 in next_formulas:
            for nf2 in next_formulas:
                if isinstance(nf2.formula, ConnectiveFormula) and nf2.formula.connective == LogicalConnective.IMPLIES:
                    if len(nf2.formula.formulas) == 2:
                        if nf1.formula == nf2.formula.formulas[0]:
                            return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        next_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "NEXT"]
        
        for nf1 in next_formulas:
            for nf2 in next_formulas:
                if isinstance(nf2.formula, ConnectiveFormula) and nf2.formula.connective == LogicalConnective.IMPLIES:
                    if len(nf2.formula.formulas) == 2:
                        if nf1.formula == nf2.formula.formulas[0]:
                            # ○P and ○(P→Q) → ○Q
                            new_next = TemporalFormula(nf1.operator, nf2.formula.formulas[1])
                            results.append(new_next)
        return results


# ==============================================================================
# Until and Since Operators
# ==============================================================================

class UntilWeakening(InferenceRule):
    """Until Weakening: P U Q ⊢ ◊Q
    
    If P holds until Q, then Q eventually holds.
    """
    
    def name(self) -> str:
        return "Until Weakening"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "UNTIL":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "UNTIL":
                # P U Q → ◊Q (the second argument eventually holds)
                if isinstance(f.formula, ConnectiveFormula) and len(f.formula.formulas) >= 2:
                    eventually_q = TemporalFormula(TemporalOperator.EVENTUALLY, f.formula.formulas[1])
                    results.append(eventually_q)
        return results


class SinceWeakening(InferenceRule):
    """Since Weakening: P S Q ⊢ ◊Q (in the past)
    
    If P has held since Q, then Q held at some past time.
    """
    
    def name(self) -> str:
        return "Since Weakening"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "SINCE":
                return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, TemporalFormula) and f.operator.value == "SINCE":
                # P S Q → Q held in the past
                # For simplicity, we derive that Q held (without explicit past operator)
                if isinstance(f.formula, ConnectiveFormula) and len(f.formula.formulas) >= 2:
                    results.append(f.formula.formulas[1])
        return results


class TemporalUntilElimination(InferenceRule):
    """Temporal Until Elimination: P U Q ∧ Q ⊢ Q
    
    If P holds until Q, and Q currently holds, then Q holds.
    """
    
    def name(self) -> str:
        return "Temporal Until Elimination"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        until_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "UNTIL"]
        
        for uf in until_formulas:
            if isinstance(uf.formula, ConnectiveFormula) and len(uf.formula.formulas) >= 2:
                q = uf.formula.formulas[1]
                if q in formulas:
                    return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        until_formulas = [f for f in formulas if isinstance(f, TemporalFormula) and f.operator.value == "UNTIL"]
        
        for uf in until_formulas:
            if isinstance(uf.formula, ConnectiveFormula) and len(uf.formula.formulas) >= 2:
                q = uf.formula.formulas[1]
                if q in formulas:
                    # P U Q and Q → Q
                    results.append(q)
        return results


# ==============================================================================
# Temporal Negation
# ==============================================================================

class TemporalNegation(InferenceRule):
    """Temporal Negation: ¬□P ⊢ ◊¬P
    
    If it's not always P, then eventually not-P.
    """
    
    def name(self) -> str:
        return "Temporal Negation"
    
    def can_apply(self, formulas: List[Formula]) -> bool:
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) > 0:
                    inner = f.formulas[0]
                    if isinstance(inner, TemporalFormula) and inner.operator.value == "ALWAYS":
                        return True
        return False
    
    def apply(self, formulas: List[Formula]) -> List[Formula]:
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, ConnectiveFormula) and f.connective == LogicalConnective.NOT:
                if len(f.formulas) > 0:
                    inner = f.formulas[0]
                    if isinstance(inner, TemporalFormula) and inner.operator.value == "ALWAYS":
                        # ¬□P → ◊¬P
                        negated_formula = ConnectiveFormula(LogicalConnective.NOT, [inner.formula])
                        eventually_not = TemporalFormula(TemporalOperator.EVENTUALLY, negated_formula)
                        results.append(eventually_not)
        return results


# Export all temporal rules
__all__ = [
    # Always rules
    'AlwaysDistribution',
    'AlwaysImplication',
    'AlwaysTransitive',
    'AlwaysImpliesNext',
    'AlwaysInduction',
    # Eventually rules
    'EventuallyFromAlways',
    'EventuallyDistribution',
    'EventuallyTransitive',
    'EventuallyImplication',
    # Next rules
    'NextDistribution',
    'NextImplication',
    # Until/Since rules
    'UntilWeakening',
    'SinceWeakening',
    'TemporalUntilElimination',
    # Negation
    'TemporalNegation',
]
