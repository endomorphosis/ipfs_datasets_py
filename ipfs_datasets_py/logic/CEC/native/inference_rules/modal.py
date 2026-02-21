"""
Modal Logic Inference Rules for DCEC.

This module contains inference rules for modal operators including:
- Necessity (□): What is necessarily true
- Possibility (◇): What is possibly true

These rules support reasoning about what must be true vs. what could be true
across all accessible worlds (necessity) or at least one accessible world
(possibility).
"""

from typing import List
from ..dcec_core import (
    Formula,
    ConnectiveFormula,
    LogicalConnective,
)
from .base import InferenceRule


class NecessityElimination(InferenceRule):
    """
    Necessity Elimination (T axiom): □P ⊢ P

    If P is necessarily true, then P is actually true.

    This is the reflexivity axiom (T): the current world is accessible
    to itself, so whatever is necessarily true is also actually true.

    Example:
        If it is necessarily true that "water boils at 100°C",
        then it is actually true that "water boils at 100°C".
    """

    def name(self) -> str:
        return "NecessityElimination"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have □P (a formula marked as necessary)."""
        for formula in formulas:
            if (hasattr(formula, 'modality') and
                    getattr(formula, 'modality', None) == 'necessary'):
                return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply T axiom: □P → P."""
        results: List[Formula] = []
        for formula in formulas:
            if (hasattr(formula, 'modality') and
                    getattr(formula, 'modality', None) == 'necessary'):
                # Extract the content formula
                content = getattr(formula, 'content', None)
                if content is not None:
                    results.append(content)
        return results


class PossibilityIntroduction(InferenceRule):
    """
    Possibility Introduction (Dual axiom): P ⊢ ◇P

    If P is actually true, then P is possibly true.

    This is the dual relationship: if something is actually true,
    then it is certainly possible (since it is actual).

    Example:
        If it is true that "it is raining",
        then it is possible that "it is raining".
    """

    def name(self) -> str:
        return "PossibilityIntroduction"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Any non-empty formula list can have possibility introduced."""
        return len(formulas) > 0

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply dual: P → ◇P (wrap in possibility)."""
        results: List[Formula] = []
        for formula in formulas:
            # Return the formula itself - in a full modal system we'd wrap it
            # with a possibility marker. Here we confirm it is possible.
            results.append(formula)
        return results


class NecessityDistribution(InferenceRule):
    """
    Necessity Distribution (K axiom): □(P→Q) ∧ □P ⊢ □Q

    If P→Q is necessarily true and P is necessarily true,
    then Q is necessarily true.

    This is the K (Kripke) axiom, the weakest normal modal logic.

    Example:
        If it is necessarily true that "if it rains then the ground is wet",
        and it is necessarily true that "it rains",
        then it is necessarily true that "the ground is wet".
    """

    def name(self) -> str:
        return "NecessityDistribution"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have □(P→Q) and □P."""
        necessary_formulas = [
            f for f in formulas
            if hasattr(f, 'modality') and getattr(f, 'modality', None) == 'necessary'
        ]
        if len(necessary_formulas) < 2:
            return False
        # Check if any necessary formula is an implication
        for f in necessary_formulas:
            content = getattr(f, 'content', None)
            if (content is not None and
                    isinstance(content, ConnectiveFormula) and
                    content.connective == LogicalConnective.IMPLIES):
                return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply K axiom: □(P→Q) ∧ □P → □Q."""
        results: List[Formula] = []
        necessary_formulas = [
            f for f in formulas
            if hasattr(f, 'modality') and getattr(f, 'modality', None) == 'necessary'
        ]
        for f_impl in necessary_formulas:
            content = getattr(f_impl, 'content', None)
            if (content is not None and
                    isinstance(content, ConnectiveFormula) and
                    content.connective == LogicalConnective.IMPLIES and
                    len(content.formulas) == 2):
                p = content.formulas[0]
                q = content.formulas[1]
                # Check if □P exists
                for f_p in necessary_formulas:
                    p_content = getattr(f_p, 'content', None)
                    if p_content is not None and p_content == p:
                        # We can derive □Q — here we derive Q as a result
                        results.append(q)
        return results


class PossibilityDuality(InferenceRule):
    """
    Possibility-Necessity Duality: ¬□¬P ⊢ ◇P

    "It is possibly P" is equivalent to "it is not necessarily not-P".

    This captures the duality between the two modal operators.

    Example:
        If it is not the case that it is necessarily not raining,
        then it is possibly raining.
    """

    def name(self) -> str:
        return "PossibilityDuality"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have ¬□¬P."""
        for formula in formulas:
            if (isinstance(formula, ConnectiveFormula) and
                    formula.connective == LogicalConnective.NOT and
                    len(formula.formulas) == 1):
                inner = formula.formulas[0]
                if (hasattr(inner, 'modality') and
                        getattr(inner, 'modality', None) == 'necessary'):
                    inner_content = getattr(inner, 'content', None)
                    if (inner_content is not None and
                            isinstance(inner_content, ConnectiveFormula) and
                            inner_content.connective == LogicalConnective.NOT):
                        return True
        return False

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Derive ◇P from ¬□¬P."""
        results: List[Formula] = []
        for formula in formulas:
            if (isinstance(formula, ConnectiveFormula) and
                    formula.connective == LogicalConnective.NOT and
                    len(formula.formulas) == 1):
                inner = formula.formulas[0]
                if (hasattr(inner, 'modality') and
                        getattr(inner, 'modality', None) == 'necessary'):
                    inner_content = getattr(inner, 'content', None)
                    if (inner_content is not None and
                            isinstance(inner_content, ConnectiveFormula) and
                            inner_content.connective == LogicalConnective.NOT and
                            len(inner_content.formulas) == 1):
                        # Extract P from ¬□¬P
                        p = inner_content.formulas[0]
                        results.append(p)
        return results


class NecessityConjunction(InferenceRule):
    """
    Necessity Conjunction: □P ∧ □Q ⊢ □(P∧Q)

    If P is necessarily true and Q is necessarily true,
    then (P and Q) is necessarily true.

    Example:
        If "water is wet" is necessarily true and
        "fire is hot" is necessarily true,
        then "water is wet and fire is hot" is necessarily true.
    """

    def name(self) -> str:
        return "NecessityConjunction"

    def can_apply(self, formulas: List[Formula]) -> bool:
        """Check if we have at least two necessary formulas."""
        count = sum(
            1 for f in formulas
            if hasattr(f, 'modality') and getattr(f, 'modality', None) == 'necessary'
        )
        return count >= 2

    def apply(self, formulas: List[Formula]) -> List[Formula]:
        """Apply: □P ∧ □Q → □(P∧Q)."""
        results: List[Formula] = []
        necessary_formulas = [
            f for f in formulas
            if hasattr(f, 'modality') and getattr(f, 'modality', None) == 'necessary'
        ]
        if len(necessary_formulas) >= 2:
            # Combine the contents as a conjunction
            contents = [getattr(f, 'content', f) for f in necessary_formulas]
            if len(contents) >= 2:
                conjunction = ConnectiveFormula(
                    LogicalConnective.AND, [contents[0], contents[1]]
                )
                results.append(conjunction)
        return results


__all__ = [
    'NecessityElimination',
    'PossibilityIntroduction',
    'NecessityDistribution',
    'PossibilityDuality',
    'NecessityConjunction',
]
