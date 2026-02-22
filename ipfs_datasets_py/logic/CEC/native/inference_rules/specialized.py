"""
Specialized Inference Rules for DCEC.

This module contains advanced and specialized inference rules including:
- Biconditional Introduction/Elimination
- Constructive and Destructive Dilemma
- Exportation (Importation)
- Absorption
- Addition (Disjunction Introduction)
- Tautology
- Commutativity and Associativity of conjunction/disjunction

These rules extend the core propositional calculus with additional
derived rules for common proof patterns.
"""

from typing import List
from ..dcec_core import (
    Formula,
    ConnectiveFormula,
    LogicalConnective,
)
from .base import InferenceRule


class BiconditionalIntroduction(InferenceRule):
    """
    Biconditional Introduction: (P→Q) ∧ (Q→P) ⊢ P↔Q

    If P implies Q and Q implies P, then P and Q are logically equivalent.

    Example:
        From "If it rains, the ground is wet" and
        "If the ground is wet, it rained",
        derive "It rains if and only if the ground is wet".
    """

    def name(self) -> str:
        return "BiconditionalIntroduction"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have both P→Q and Q→P."""
        implications = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.IMPLIES and
            len(f.formulas) == 2
        ]
        for i, impl1 in enumerate(implications):
            p1, q1 = impl1.formulas[0], impl1.formulas[1]
            for impl2 in implications[i + 1:]:
                p2, q2 = impl2.formulas[0], impl2.formulas[1]
                if p1 == q2 and q1 == p2:
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply biconditional introduction."""
        results: List[Formula] = []
        implications = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.IMPLIES and
            len(f.formulas) == 2
        ]
        added: List[str] = []
        for i, impl1 in enumerate(implications):
            p1, q1 = impl1.formulas[0], impl1.formulas[1]
            for impl2 in implications[i + 1:]:
                p2, q2 = impl2.formulas[0], impl2.formulas[1]
                if p1 == q2 and q1 == p2:
                    key = f"{id(p1)}-{id(q1)}"
                    if key not in added:
                        results.append(
                            ConnectiveFormula(
                                LogicalConnective.BICONDITIONAL, [p1, q1]
                            )
                        )
                        added.append(key)
        return results


class BiconditionalElimination(InferenceRule):
    """
    Biconditional Elimination: P↔Q ⊢ (P→Q) ∧ (Q→P)

    A biconditional can be split into two implications.

    Example:
        From "It rains if and only if the ground is wet",
        derive "If it rains, the ground is wet" and
        "If the ground is wet, it rained".
    """

    def name(self) -> str:
        return "BiconditionalElimination"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have a biconditional."""
        return any(
            isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.BICONDITIONAL
            for f in formulas
        )

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply biconditional elimination: P↔Q → (P→Q) ∧ (Q→P)."""
        results: List[Formula] = []
        for formula in formulas:
            if (isinstance(formula, ConnectiveFormula) and
                    formula.connective == LogicalConnective.BICONDITIONAL and
                    len(formula.formulas) == 2):
                p, q = formula.formulas[0], formula.formulas[1]
                results.append(ConnectiveFormula(LogicalConnective.IMPLIES, [p, q]))
                results.append(ConnectiveFormula(LogicalConnective.IMPLIES, [q, p]))
        return results


class ConstructiveDilemma(InferenceRule):
    """
    Constructive Dilemma: (P→Q) ∧ (R→S) ∧ (P∨R) ⊢ (Q∨S)

    If P implies Q, R implies S, and either P or R is true,
    then either Q or S must be true.

    Example:
        From "If it rains we take an umbrella",
        "If it's sunny we wear sunglasses",
        and "It is either raining or sunny",
        derive "We either have an umbrella or wear sunglasses".
    """

    def name(self) -> str:
        return "ConstructiveDilemma"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check for (P→Q), (R→S), (P∨R) pattern."""
        implications = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.IMPLIES and
            len(f.formulas) == 2
        ]
        disjunctions = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.OR and
            len(f.formulas) >= 2
        ]
        if len(implications) < 2 or not disjunctions:
            return False
        for i, impl1 in enumerate(implications):
            for impl2 in implications[i + 1:]:
                p, r = impl1.formulas[0], impl2.formulas[0]
                for disj in disjunctions:
                    if (p in disj.formulas and r in disj.formulas):
                        return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply constructive dilemma."""
        results: List[Formula] = []
        implications = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.IMPLIES and
            len(f.formulas) == 2
        ]
        disjunctions = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.OR and
            len(f.formulas) >= 2
        ]
        for i, impl1 in enumerate(implications):
            for impl2 in implications[i + 1:]:
                p, q = impl1.formulas[0], impl1.formulas[1]
                r, s = impl2.formulas[0], impl2.formulas[1]
                for disj in disjunctions:
                    if p in disj.formulas and r in disj.formulas:
                        results.append(
                            ConnectiveFormula(LogicalConnective.OR, [q, s])
                        )
        return results


class DestructiveDilemma(InferenceRule):
    """
    Destructive Dilemma: (P→Q) ∧ (R→S) ∧ (¬Q∨¬S) ⊢ (¬P∨¬R)

    If P implies Q, R implies S, and either Q or S is false,
    then either P or R must be false.

    Example:
        From "If it rains we take an umbrella",
        "If it's sunny we wear sunglasses",
        and "We don't have an umbrella or we don't wear sunglasses",
        derive "It's not raining or it's not sunny".
    """

    def name(self) -> str:
        return "DestructiveDilemma"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check for (P→Q), (R→S), (¬Q∨¬S) pattern."""
        implications = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.IMPLIES and
            len(f.formulas) == 2
        ]
        disjunctions = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.OR
        ]
        if len(implications) < 2 or not disjunctions:
            return False
        for i, impl1 in enumerate(implications):
            for impl2 in implications[i + 1:]:
                q = impl1.formulas[1]
                s = impl2.formulas[1]
                not_q = ConnectiveFormula(LogicalConnective.NOT, [q])
                not_s = ConnectiveFormula(LogicalConnective.NOT, [s])
                for disj in disjunctions:
                    disj_lits = list(disj.formulas)
                    if (any(l == not_q for l in disj_lits) and
                            any(l == not_s for l in disj_lits)):
                        return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply destructive dilemma."""
        results: List[Formula] = []
        implications = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.IMPLIES and
            len(f.formulas) == 2
        ]
        disjunctions = [
            f for f in formulas
            if isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.OR
        ]
        for i, impl1 in enumerate(implications):
            for impl2 in implications[i + 1:]:
                p, q = impl1.formulas[0], impl1.formulas[1]
                r, s = impl2.formulas[0], impl2.formulas[1]
                not_q = ConnectiveFormula(LogicalConnective.NOT, [q])
                not_s = ConnectiveFormula(LogicalConnective.NOT, [s])
                for disj in disjunctions:
                    disj_lits = list(disj.formulas)
                    if (any(l == not_q for l in disj_lits) and
                            any(l == not_s for l in disj_lits)):
                        not_p = ConnectiveFormula(LogicalConnective.NOT, [p])
                        not_r = ConnectiveFormula(LogicalConnective.NOT, [r])
                        results.append(
                            ConnectiveFormula(LogicalConnective.OR, [not_p, not_r])
                        )
        return results


class ExportationRule(InferenceRule):
    """
    Exportation: (P∧Q)→R ⊢ P→(Q→R)

    An implication from a conjunction can be rewritten as a chain of
    implications (currying).

    Example:
        From "If Alice is home and Bob calls, Alice answers",
        derive "If Alice is home, then if Bob calls, Alice answers".
    """

    def name(self) -> str:
        return "Exportation"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have (P∧Q)→R."""
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.IMPLIES and
                    len(f.formulas) == 2):
                antecedent = f.formulas[0]
                if (isinstance(antecedent, ConnectiveFormula) and
                        antecedent.connective == LogicalConnective.AND):
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply exportation: (P∧Q)→R → P→(Q→R)."""
        results: List[Formula] = []
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.IMPLIES and
                    len(f.formulas) == 2):
                antecedent = f.formulas[0]
                r = f.formulas[1]
                if (isinstance(antecedent, ConnectiveFormula) and
                        antecedent.connective == LogicalConnective.AND and
                        len(antecedent.formulas) >= 2):
                    p = antecedent.formulas[0]
                    q = antecedent.formulas[1]
                    # P → (Q → R)
                    q_implies_r = ConnectiveFormula(LogicalConnective.IMPLIES, [q, r])
                    results.append(
                        ConnectiveFormula(LogicalConnective.IMPLIES, [p, q_implies_r])
                    )
        return results


class AbsorptionRule(InferenceRule):
    """
    Absorption: P→Q ⊢ P→(P∧Q)

    If P implies Q, then P implies (P and Q).

    Example:
        From "If it rains, the ground is wet",
        derive "If it rains, it is raining and the ground is wet".
    """

    def name(self) -> str:
        return "Absorption"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have P→Q."""
        return any(
            isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.IMPLIES and
            len(f.formulas) == 2
            for f in formulas
        )

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply absorption: P→Q → P→(P∧Q)."""
        results: List[Formula] = []
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.IMPLIES and
                    len(f.formulas) == 2):
                p, q = f.formulas[0], f.formulas[1]
                p_and_q = ConnectiveFormula(LogicalConnective.AND, [p, q])
                results.append(
                    ConnectiveFormula(LogicalConnective.IMPLIES, [p, p_and_q])
                )
        return results


class AdditionRule(InferenceRule):
    """
    Addition (Disjunction Introduction): P ⊢ P∨Q

    From a formula P, we can always introduce a disjunction P∨Q,
    since if P is true then P∨Q is true regardless of Q.

    Example:
        From "Alice is home",
        derive "Alice is home or Bob is visiting".
    """

    def name(self) -> str:
        return "Addition"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Any non-empty formula list can have addition applied."""
        return len(formulas) > 0

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply addition — returns the formulas as potential disjuncts."""
        # In practice, addition requires knowing Q (the added disjunct).
        # We return the formulas themselves as the possible disjuncts.
        return list(formulas)


class TautologyRule(InferenceRule):
    """
    Tautology: P∨P ⊢ P

    A disjunction of a formula with itself simplifies to that formula.

    Example:
        From "Alice is home or Alice is home",
        derive "Alice is home".
    """

    def name(self) -> str:
        return "Tautology"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have P∨P."""
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.OR and
                    len(f.formulas) >= 2):
                if all(lit == f.formulas[0] for lit in f.formulas):
                    return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply tautology simplification: P∨P → P."""
        results: List[Formula] = []
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.OR and
                    len(f.formulas) >= 2):
                if all(lit == f.formulas[0] for lit in f.formulas):
                    results.append(f.formulas[0])
        return results


class CommutativityConjunction(InferenceRule):
    """
    Commutativity of Conjunction: P∧Q ⊢ Q∧P

    The order of conjuncts does not matter.

    Example:
        From "Alice is home and Bob is visiting",
        derive "Bob is visiting and Alice is home".
    """

    def name(self) -> str:
        return "CommutativityConjunction"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have a conjunction."""
        return any(
            isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.AND and
            len(f.formulas) == 2
            for f in formulas
        )

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply commutativity: P∧Q → Q∧P."""
        results: List[Formula] = []
        for f in formulas:
            if (isinstance(f, ConnectiveFormula) and
                    f.connective == LogicalConnective.AND and
                    len(f.formulas) == 2):
                p, q = f.formulas[0], f.formulas[1]
                results.append(ConnectiveFormula(LogicalConnective.AND, [q, p]))
        return results


__all__ = [
    'ConstructiveDilemma',
    'DestructiveDilemma',
    'ExportationRule',
    'AbsorptionRule',
    'AdditionRule',
    'TautologyRule',
    'CommutativityConjunction',
]
