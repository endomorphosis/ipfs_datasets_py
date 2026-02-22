"""
Resolution-Based Inference Rules for DCEC.

This module contains resolution-based inference rules including:
- Resolution: The primary rule in resolution-based theorem proving
- Unit Resolution: Simplified resolution with unit clauses
- Binary Resolution: Resolution between two clauses
- Factoring: Reduction of duplicate literals in a clause
- Subsumption: Clause simplification by subsumed clauses
- Case Analysis: Proof by cases (disjunction elimination)
- Proof by Contradiction: Reductio ad absurdum

These rules are particularly useful for automated theorem proving
using the resolution calculus.
"""

from typing import List, Optional
from ..dcec_core import (
    Formula,
    ConnectiveFormula,
    LogicalConnective,
)
from .base import InferenceRule


class ResolutionRule(InferenceRule):
    """
    Resolution: (P ∨ Q) ∧ (¬P ∨ R) ⊢ (Q ∨ R)

    The resolution rule combines two clauses by eliminating a complementary
    literal pair (P and ¬P), producing a resolvent clause.

    This is the fundamental rule of resolution-based theorem proving,
    capable of generating complete proofs for first-order logic.

    Example:
        From "Alice is at home or Alice is at work"
        and "Alice is not at home or Alice is busy",
        derive "Alice is at work or Alice is busy".
    """

    def name(self) -> str:
        return "Resolution"

    def _get_disjuncts(self, formula: Formula) -> Optional[List[Formula]]:
        """Extract disjuncts from a clause (OR formula)."""
        if isinstance(formula, ConnectiveFormula):
            if formula.connective == LogicalConnective.OR:
                return list(formula.formulas)
        return None

    def _is_negation_of(self, f1: Formula, f2: Formula) -> bool:
        """Check if f1 is the negation of f2."""
        if (isinstance(f1, ConnectiveFormula) and
                f1.connective == LogicalConnective.NOT and
                len(f1.formulas) == 1):
            return f1.formulas[0] == f2
        return False

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if resolution can be applied to any pair of clauses."""
        clauses = [f for f in formulas if isinstance(f, ConnectiveFormula)
                   and f.connective == LogicalConnective.OR]
        if len(clauses) < 2:
            return False
        for i, c1 in enumerate(clauses):
            d1 = self._get_disjuncts(c1) or []
            for c2 in clauses[i + 1:]:
                d2 = self._get_disjuncts(c2) or []
                for lit1 in d1:
                    for lit2 in d2:
                        if self._is_negation_of(lit1, lit2) or self._is_negation_of(lit2, lit1):
                            return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply resolution to produce resolvent clauses."""
        results: List[Formula] = []
        clauses = [f for f in formulas if isinstance(f, ConnectiveFormula)
                   and f.connective == LogicalConnective.OR]
        for i, c1 in enumerate(clauses):
            d1 = self._get_disjuncts(c1) or []
            for c2 in clauses[i + 1:]:
                d2 = self._get_disjuncts(c2) or []
                for j, lit1 in enumerate(d1):
                    for k, lit2 in enumerate(d2):
                        if self._is_negation_of(lit1, lit2) or self._is_negation_of(lit2, lit1):
                            # Create resolvent: (d1 - lit1) ∨ (d2 - lit2)
                            remaining = ([f for idx, f in enumerate(d1) if idx != j] +
                                         [f for idx, f in enumerate(d2) if idx != k])
                            if len(remaining) == 0:
                                # Empty clause — contradiction found
                                pass
                            elif len(remaining) == 1:
                                results.append(remaining[0])
                            else:
                                results.append(
                                    ConnectiveFormula(LogicalConnective.OR, remaining)
                                )
        return results


class UnitResolutionRule(InferenceRule):
    """
    Unit Resolution: P ∧ (¬P ∨ Q) ⊢ Q

    A specialization of resolution where one clause is a unit (single literal).
    This is more efficient than general resolution.

    Example:
        From "Alice is at home" and
        "Alice is not at home or Alice is busy",
        derive "Alice is busy".
    """

    def name(self) -> str:
        return "UnitResolution"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if unit resolution can be applied."""
        # Look for unit literal P and clause containing ¬P
        for unit in formulas:
            if isinstance(unit, ConnectiveFormula) and unit.connective == LogicalConnective.OR:
                continue  # Not a unit literal
            for clause in formulas:
                if (isinstance(clause, ConnectiveFormula) and
                        clause.connective == LogicalConnective.OR):
                    for lit in clause.formulas:
                        if (isinstance(lit, ConnectiveFormula) and
                                lit.connective == LogicalConnective.NOT and
                                len(lit.formulas) == 1 and
                                lit.formulas[0] == unit):
                            return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply unit resolution."""
        results: List[Formula] = []
        units = [f for f in formulas
                 if not (isinstance(f, ConnectiveFormula) and
                         f.connective == LogicalConnective.OR)]
        for unit in units:
            for clause in formulas:
                if (isinstance(clause, ConnectiveFormula) and
                        clause.connective == LogicalConnective.OR):
                    remaining = []
                    resolved = False
                    for lit in clause.formulas:
                        if (isinstance(lit, ConnectiveFormula) and
                                lit.connective == LogicalConnective.NOT and
                                len(lit.formulas) == 1 and
                                lit.formulas[0] == unit):
                            resolved = True
                        else:
                            remaining.append(lit)
                    if resolved:
                        if len(remaining) == 1:
                            results.append(remaining[0])
                        elif len(remaining) > 1:
                            results.append(
                                ConnectiveFormula(LogicalConnective.OR, remaining)
                            )
        return results


class FactoringRule(InferenceRule):
    """
    Factoring: (P ∨ P ∨ Q) ⊢ (P ∨ Q)

    Removes duplicate literals from a clause (disjunction).
    This simplifies clauses by eliminating redundancy.

    Example:
        From "Alice is busy or Alice is busy or Alice is tired",
        derive "Alice is busy or Alice is tired".
    """

    def name(self) -> str:
        return "Factoring"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if any clause has duplicate literals."""
        for formula in formulas:
            if (isinstance(formula, ConnectiveFormula) and
                    formula.connective == LogicalConnective.OR):
                seen = []
                for lit in formula.formulas:
                    if lit in seen:
                        return True
                    seen.append(lit)
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply factoring to remove duplicate literals."""
        results: List[Formula] = []
        for formula in formulas:
            if (isinstance(formula, ConnectiveFormula) and
                    formula.connective == LogicalConnective.OR):
                seen: List[Formula] = []
                changed = False
                for lit in formula.formulas:
                    if lit not in seen:
                        seen.append(lit)
                    else:
                        changed = True
                if changed:
                    if len(seen) == 1:
                        results.append(seen[0])
                    else:
                        results.append(ConnectiveFormula(LogicalConnective.OR, seen))
        return results


class SubsumptionRule(InferenceRule):
    """
    Subsumption: If C1 ⊆ C2 (as clauses), then C2 can be removed.

    If clause C1 is a subset of clause C2, then C2 is subsumed by C1
    and can be removed (C1 is more general).

    This is a simplification rule that removes redundant clauses.

    Example:
        Clause "P ∨ Q" subsumes "P ∨ Q ∨ R" because every model
        satisfying "P ∨ Q" also satisfies "P ∨ Q ∨ R".
    """

    def name(self) -> str:
        return "Subsumption"

    def _clause_subsumes(self, c1: Formula, c2: Formula) -> bool:
        """Check if c1 subsumes c2 (c1 ⊆ c2 as literal sets)."""
        if c1 == c2:
            return False  # Same clause, no simplification
        d1 = (list(c1.formulas) if isinstance(c1, ConnectiveFormula) and
              c1.connective == LogicalConnective.OR else [c1])
        d2 = (list(c2.formulas) if isinstance(c2, ConnectiveFormula) and
              c2.connective == LogicalConnective.OR else [c2])
        # c1 subsumes c2 if every literal in c1 appears in c2
        return all(any(l1 == l2 for l2 in d2) for l1 in d1) and len(d1) < len(d2)

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if any clause is subsumed by another."""
        for i, c1 in enumerate(formulas):
            for c2 in formulas[i + 1:]:
                if self._clause_subsumes(c1, c2) or self._clause_subsumes(c2, c1):
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Return the non-subsumed (more general) clauses."""
        results: List[Formula] = []
        subsumed = set()
        for i, c1 in enumerate(formulas):
            for j, c2 in enumerate(formulas):
                if i != j and self._clause_subsumes(c1, c2):
                    subsumed.add(j)
        # Keep only the subsuming (shorter) clauses
        for i, f in enumerate(formulas):
            if i not in subsumed:
                results.append(f)
        return results


class CaseAnalysisRule(InferenceRule):
    """
    Case Analysis (Disjunction Elimination): (P ∨ Q) ∧ (P→R) ∧ (Q→R) ⊢ R

    If we know P or Q is true, and in both cases R follows,
    then R must be true.

    Also known as proof by cases or constructive dilemma.

    Example:
        From "Alice is home or Alice is at work",
        "If Alice is home, she is reachable",
        "If Alice is at work, she is reachable",
        derive "Alice is reachable".
    """

    def name(self) -> str:
        return "CaseAnalysis"

    def _find_implication(self, formulas: List[Formula],
                          antecedent: Formula) -> Optional[Formula]:
        """Find P→R in formulas where antecedent matches P."""
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.IMPLIES and
                    len(f.formulas) == 2 and
                    f.formulas[0] == antecedent):
                return f.formulas[1]
        return None

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check for P∨Q, P→R, Q→R pattern."""
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.OR and
                    len(f.formulas) >= 2):
                p = f.formulas[0]
                q = f.formulas[1]
                r1 = self._find_implication(formulas, p)
                r2 = self._find_implication(formulas, q)
                if r1 is not None and r2 is not None and r1 == r2:
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply case analysis to derive R from P∨Q, P→R, Q→R."""
        results: List[Formula] = []
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.OR and
                    len(f.formulas) >= 2):
                p = f.formulas[0]
                q = f.formulas[1]
                r1 = self._find_implication(formulas, p)
                r2 = self._find_implication(formulas, q)
                if r1 is not None and r2 is not None and r1 == r2:
                    results.append(r1)
        return results


class ProofByContradictionRule(InferenceRule):
    """
    Proof by Contradiction (Reductio ad Absurdum): If ¬P ⊢ ⊥, then ⊢ P

    If assuming the negation of P leads to a contradiction,
    then P must be true.

    Represented here as: {¬P, Q, ¬Q} ⊢ P

    Example:
        If we assume Alice is not at home and derive both
        "Alice is busy" and "Alice is not busy",
        we have a contradiction, so Alice must be at home.
    """

    def name(self) -> str:
        return "ProofByContradiction"

    def _find_contradicting_formulas(
        self, formulas: List[Formula]
    ) -> Optional[Formula]:
        """Find a formula and its negation."""
        for i, f1 in enumerate(formulas):
            for f2 in formulas[i + 1:]:
                if (isinstance(f2, ConnectiveFormula) and
                        f2.connective == LogicalConnective.NOT and
                        len(f2.formulas) == 1 and
                        f2.formulas[0] == f1):
                    return f1
                if (isinstance(f1, ConnectiveFormula) and
                        f1.connective == LogicalConnective.NOT and
                        len(f1.formulas) == 1 and
                        f1.formulas[0] == f2):
                    return f2
        return None

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if there is a contradiction in the formula set."""
        return self._find_contradicting_formulas(formulas) is not None

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply proof by contradiction: contradiction found, negate the assumption."""
        # In a real system this would negate the most recently added assumption.
        # Here we just signal that a contradiction was found by returning empty.
        # The caller can use the ProofResult.PROVED on the negated assumption.
        return []


__all__ = [
    'ResolutionRule',
    'UnitResolutionRule',
    'FactoringRule',
    'SubsumptionRule',
    'CaseAnalysisRule',
    'ProofByContradictionRule',
]
