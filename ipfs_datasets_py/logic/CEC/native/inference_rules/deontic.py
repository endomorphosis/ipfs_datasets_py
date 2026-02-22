"""
Deontic Logic Inference Rules for CEC.

This module contains inference rules for deontic logic, which deals with:
- Obligation (O): something that must be done
- Permission (P): something that may be done
- Prohibition (F): something that must not be done

Deontic operators capture normative reasoning about rights, duties, and permissions.

Author: CEC Native Refactoring
Date: 2026-02-19
"""

from typing import List
from .base import InferenceRule
from ..dcec_core import (
    Formula, DeonticFormula, ConnectiveFormula,
    DeonticOperator, LogicalConnective,
)


class ObligationDistribution(InferenceRule):
    """
    Obligation distributes over conjunction.

    Rule: O(P∧Q) ⊢ O(P) ∧ O(Q)

    If there is an obligation to do both P and Q, then there is an obligation
    to do P and an obligation to do Q separately.

    Example:
        O(study ∧ exercise) ⊢ O(study) ∧ O(exercise)
    """

    def name(self) -> str:
        return "Obligation Distribution"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if obligation distribution can be applied."""
        for f in formulas:
            if (isinstance(f, DeonticFormula) and
                    f.operator == DeonticOperator.OBLIGATION and
                    isinstance(f.formula, ConnectiveFormula) and
                    f.formula.connective == LogicalConnective.AND):
                return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply obligation distribution rule."""
        for f in formulas:
            if (isinstance(f, DeonticFormula) and
                    f.operator == DeonticOperator.OBLIGATION and
                    isinstance(f.formula, ConnectiveFormula) and
                    f.formula.connective == LogicalConnective.AND):
                # O(P∧Q) → O(P) ∧ O(Q)
                sub = f.formula.formulas
                oblig_parts = [DeonticFormula(DeonticOperator.OBLIGATION, s) for s in sub]
                return [ConnectiveFormula(LogicalConnective.AND, oblig_parts)]
        return []


class ObligationImplication(InferenceRule):
    """
    Obligation propagates through implication.

    Rule: O(P) ∧ (P→Q) ⊢ O(Q)

    If there is an obligation to do P, and P implies Q, then there is an
    obligation to do Q.

    Example:
        O(attend_class) ∧ (attend_class → arrive_early) ⊢ O(arrive_early)
    """

    def name(self) -> str:
        return "Obligation Implication"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if obligation implication can be applied."""
        obligations = [f for f in formulas if isinstance(f, DeonticFormula)
                       and f.operator == DeonticOperator.OBLIGATION]
        implications = [f for f in formulas if isinstance(f, ConnectiveFormula)
                        and f.connective == LogicalConnective.IMPLIES
                        and len(f.formulas) == 2]
        for obl in obligations:
            for impl in implications:
                if impl.formulas[0] == obl.formula:
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply obligation implication rule."""
        obligations = [f for f in formulas if isinstance(f, DeonticFormula)
                       and f.operator == DeonticOperator.OBLIGATION]
        implications = [f for f in formulas if isinstance(f, ConnectiveFormula)
                        and f.connective == LogicalConnective.IMPLIES
                        and len(f.formulas) == 2]
        results: List[Formula] = []
        for obl in obligations:
            for impl in implications:
                if impl.formulas[0] == obl.formula:
                    results.append(DeonticFormula(DeonticOperator.OBLIGATION, impl.formulas[1]))
        return results


class PermissionFromNonObligation(InferenceRule):
    """
    Permission is the dual of obligation.

    Rule: ¬O(¬P) ⊢ P(P)

    If it's not obligatory to not do P, then P is permitted.
    This captures the deontic duality principle.

    Example:
        ¬O(¬speak) ⊢ P(speak)
    """

    def name(self) -> str:
        return "Permission from Non-Obligation"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if permission derivation can be applied."""
        for f in formulas:
            # f must be ¬(O(¬P)) — ConnectiveFormula.NOT wrapping a DeonticFormula
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.NOT and
                    len(f.formulas) == 1):
                inner = f.formulas[0]
                if (isinstance(inner, DeonticFormula) and
                        inner.operator == DeonticOperator.OBLIGATION and
                        isinstance(inner.formula, ConnectiveFormula) and
                        inner.formula.connective == LogicalConnective.NOT):
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply permission from non-obligation rule."""
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.NOT and
                    len(f.formulas) == 1):
                inner = f.formulas[0]
                if (isinstance(inner, DeonticFormula) and
                        inner.operator == DeonticOperator.OBLIGATION and
                        isinstance(inner.formula, ConnectiveFormula) and
                        inner.formula.connective == LogicalConnective.NOT and
                        len(inner.formula.formulas) == 1):
                    # ¬O(¬P) → P(P): extract P from the inner negation
                    p_content = inner.formula.formulas[0]
                    return [DeonticFormula(DeonticOperator.PERMISSION, p_content)]
        return []


class ObligationConjunction(InferenceRule):
    """
    Combine separate obligations into a single conjunction obligation.

    Rule: O(P) ∧ O(Q) ⊢ O(P∧Q)

    If there is an obligation to do P and an obligation to do Q, then there
    is an obligation to do both P and Q.

    Example:
        O(study) ∧ O(exercise) ⊢ O(study ∧ exercise)
    """

    def name(self) -> str:
        return "Obligation Conjunction"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if obligation conjunction can be applied."""
        obligations = [f for f in formulas if isinstance(f, DeonticFormula)
                       and f.operator == DeonticOperator.OBLIGATION]
        return len(obligations) >= 2

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply obligation conjunction rule."""
        obligations = [f for f in formulas if isinstance(f, DeonticFormula)
                       and f.operator == DeonticOperator.OBLIGATION]
        if len(obligations) >= 2:
            obl1, obl2 = obligations[0], obligations[1]
            conjunction = ConnectiveFormula(LogicalConnective.AND, [obl1.formula, obl2.formula])
            return [DeonticFormula(DeonticOperator.OBLIGATION, conjunction)]
        return []


class PermissionDistribution(InferenceRule):
    """
    Permission distributes over disjunction.

    Rule: P(P∨Q) ⊢ P(P) ∨ P(Q)

    If it's permitted to do either P or Q, then either P is permitted or
    Q is permitted (or both).

    Example:
        P(coffee ∨ tea) ⊢ P(coffee) ∨ P(tea)
    """

    def name(self) -> str:
        return "Permission Distribution"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if permission distribution can be applied."""
        for f in formulas:
            if (isinstance(f, DeonticFormula) and
                    f.operator == DeonticOperator.PERMISSION and
                    isinstance(f.formula, ConnectiveFormula) and
                    f.formula.connective == LogicalConnective.OR):
                return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply permission distribution rule."""
        for f in formulas:
            if (isinstance(f, DeonticFormula) and
                    f.operator == DeonticOperator.PERMISSION and
                    isinstance(f.formula, ConnectiveFormula) and
                    f.formula.connective == LogicalConnective.OR):
                # P(P∨Q) → P(P) ∨ P(Q)
                sub = f.formula.formulas
                perm_parts = [DeonticFormula(DeonticOperator.PERMISSION, s) for s in sub]
                return [ConnectiveFormula(LogicalConnective.OR, perm_parts)]
        return []


class ObligationConsistency(InferenceRule):
    """
    Detect contradictory obligations.

    Rule: O(P) ∧ O(¬P) ⊢ ⊥

    If there is both an obligation to do P and an obligation to not do P,
    this represents an inconsistency (contradiction).  Returns an empty list
    when a contradiction is detected (the inconsistency prevents deriving
    new consistent formulas).

    Example:
        O(speak) ∧ O(¬speak) ⊢ ⊥ (inconsistent)
    """

    def name(self) -> str:
        return "Obligation Consistency"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we can detect obligation inconsistency."""
        obligations = [f for f in formulas if isinstance(f, DeonticFormula)
                       and f.operator == DeonticOperator.OBLIGATION]
        for obl1 in obligations:
            content1 = obl1.formula
            for obl2 in obligations:
                if obl1 is obl2:
                    continue
                content2 = obl2.formula
                # content2 is ¬content1 when it is ConnectiveFormula.NOT wrapping content1
                if (isinstance(content2, ConnectiveFormula) and
                        content2.connective == LogicalConnective.NOT and
                        len(content2.formulas) == 1 and
                        content2.formulas[0] == content1):
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply obligation consistency check.

        Returns an empty list to signal the inconsistency (no new formulas
        can be soundly derived from contradictory obligations).
        """
        return []


class ProhibitionEquivalence(InferenceRule):
    """
    Prohibition is equivalent to obligation of negation.

    Rule: F(P) ⊣⊢ O(¬P)

    To be forbidden from doing P is the same as being obligated to not do P.
    This is a bidirectional equivalence.

    Example:
        F(smoke) ⊣⊢ O(¬smoke)
    """

    def name(self) -> str:
        return "Prohibition Equivalence"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if prohibition equivalence can be applied."""
        for f in formulas:
            if isinstance(f, DeonticFormula):
                if f.operator == DeonticOperator.PROHIBITION:
                    return True
                if (f.operator == DeonticOperator.OBLIGATION and
                        isinstance(f.formula, ConnectiveFormula) and
                        f.formula.connective == LogicalConnective.NOT):
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply prohibition equivalence rule."""
        results: List[Formula] = []
        for f in formulas:
            if isinstance(f, DeonticFormula):
                # F(P) → O(¬P)
                if f.operator == DeonticOperator.PROHIBITION:
                    negation = ConnectiveFormula(LogicalConnective.NOT, [f.formula])
                    results.append(DeonticFormula(DeonticOperator.OBLIGATION, negation))
                # O(¬P) → F(P)
                elif (f.operator == DeonticOperator.OBLIGATION and
                      isinstance(f.formula, ConnectiveFormula) and
                      f.formula.connective == LogicalConnective.NOT and
                      len(f.formula.formulas) == 1):
                    results.append(DeonticFormula(DeonticOperator.PROHIBITION,
                                                  f.formula.formulas[0]))
        return results


# Export all deontic rules
__all__ = [
    'ObligationDistribution',
    'ObligationImplication',
    'PermissionFromNonObligation',
    'ObligationConjunction',
    'PermissionDistribution',
    'ObligationConsistency',
    'ProhibitionEquivalence',
]
