"""
TDFOL Expansion Rules - Concrete implementations for tableaux-based proof search

This module provides concrete expansion rules that can be used by both:
- Modal tableaux (ModalTableauxStrategy)
- Inference rule systems (TDFOLInferenceRules)

Phase 1 refactoring: Extracted from modal_tableaux.py to eliminate duplication.
"""

from __future__ import annotations

from typing import List, Tuple

from .tdfol_core import (
    BinaryFormula,
    DeonticFormula,
    ExpansionContext,
    ExpansionResult,
    ExpansionRule,
    Formula,
    LogicOperator,
    TemporalFormula,
    UnaryFormula,
)


class AndExpansionRule(ExpansionRule):
    """
    Expansion rule for conjunction (AND).
    
    Positive: φ ∧ ψ → φ, ψ (linear expansion)
    Negative: ¬(φ ∧ ψ) → ¬φ | ¬ψ (branching expansion)
    """
    
    def can_expand(self, formula: Formula, negated: bool = False) -> bool:
        return isinstance(formula, BinaryFormula) and formula.operator == LogicOperator.AND
    
    def expand(self, context: ExpansionContext) -> ExpansionResult:
        formula = context.formula
        assert isinstance(formula, BinaryFormula)
        
        if not context.negated:
            # φ ∧ ψ: Add both φ and ψ (linear)
            return ExpansionResult.linear(
                (formula.left, False),
                (formula.right, False)
            )
        else:
            # ¬(φ ∧ ψ): Split into ¬φ | ¬ψ (branching)
            return ExpansionResult.branching(
                [(formula.left, True)],
                [(formula.right, True)]
            )


class OrExpansionRule(ExpansionRule):
    """
    Expansion rule for disjunction (OR).
    
    Positive: φ ∨ ψ → φ | ψ (branching expansion)
    Negative: ¬(φ ∨ ψ) → ¬φ, ¬ψ (linear expansion)
    """
    
    def can_expand(self, formula: Formula, negated: bool = False) -> bool:
        return isinstance(formula, BinaryFormula) and formula.operator == LogicOperator.OR
    
    def expand(self, context: ExpansionContext) -> ExpansionResult:
        formula = context.formula
        assert isinstance(formula, BinaryFormula)
        
        if not context.negated:
            # φ ∨ ψ: Split into φ | ψ (branching)
            return ExpansionResult.branching(
                [(formula.left, False)],
                [(formula.right, False)]
            )
        else:
            # ¬(φ ∨ ψ): Add both ¬φ and ¬ψ (linear)
            return ExpansionResult.linear(
                (formula.left, True),
                (formula.right, True)
            )


class ImpliesExpansionRule(ExpansionRule):
    """
    Expansion rule for implication (IMPLIES).
    
    Positive: φ → ψ ≡ ¬φ ∨ ψ → ¬φ | ψ (branching expansion)
    Negative: ¬(φ → ψ) → φ, ¬ψ (linear expansion)
    """
    
    def can_expand(self, formula: Formula, negated: bool = False) -> bool:
        return isinstance(formula, BinaryFormula) and formula.operator == LogicOperator.IMPLIES
    
    def expand(self, context: ExpansionContext) -> ExpansionResult:
        formula = context.formula
        assert isinstance(formula, BinaryFormula)
        
        if not context.negated:
            # φ → ψ: Split into ¬φ | ψ (branching)
            return ExpansionResult.branching(
                [(formula.left, True)],
                [(formula.right, False)]
            )
        else:
            # ¬(φ → ψ): Add φ and ¬ψ (linear)
            return ExpansionResult.linear(
                (formula.left, False),
                (formula.right, True)
            )


class IffExpansionRule(ExpansionRule):
    """
    Expansion rule for bi-implication (IFF).
    
    Positive: φ ↔ ψ ≡ (φ → ψ) ∧ (ψ → φ) → (φ, ψ) | (¬φ, ¬ψ) (branching)
    Negative: ¬(φ ↔ ψ) → (φ, ¬ψ) | (¬φ, ψ) (branching)
    """
    
    def can_expand(self, formula: Formula, negated: bool = False) -> bool:
        return isinstance(formula, BinaryFormula) and formula.operator == LogicOperator.IFF
    
    def expand(self, context: ExpansionContext) -> ExpansionResult:
        formula = context.formula
        assert isinstance(formula, BinaryFormula)
        
        if not context.negated:
            # φ ↔ ψ: Split into (φ, ψ) | (¬φ, ¬ψ)
            return ExpansionResult.branching(
                [(formula.left, False), (formula.right, False)],
                [(formula.left, True), (formula.right, True)]
            )
        else:
            # ¬(φ ↔ ψ): Split into (φ, ¬ψ) | (¬φ, ψ)
            return ExpansionResult.branching(
                [(formula.left, False), (formula.right, True)],
                [(formula.left, True), (formula.right, False)]
            )


class NotExpansionRule(ExpansionRule):
    """
    Expansion rule for negation (NOT).
    
    Double negation: ¬¬φ → φ (linear expansion)
    """
    
    def can_expand(self, formula: Formula, negated: bool = False) -> bool:
        return isinstance(formula, UnaryFormula) and formula.operator == LogicOperator.NOT
    
    def expand(self, context: ExpansionContext) -> ExpansionResult:
        formula = context.formula
        assert isinstance(formula, UnaryFormula)
        
        # ¬¬φ → φ (flip negation)
        return ExpansionResult.linear(
            (formula.formula, not context.negated)
        )


# ============================================================================
# Expansion Rule Registry
# ============================================================================


def get_all_expansion_rules() -> List[ExpansionRule]:
    """
    Get all available expansion rules.
    
    Returns:
        List of expansion rule instances
    """
    return [
        AndExpansionRule(),
        OrExpansionRule(),
        ImpliesExpansionRule(),
        IffExpansionRule(),
        NotExpansionRule(),
    ]


def select_expansion_rule(formula: Formula, negated: bool = False) -> ExpansionRule | None:
    """
    Select an appropriate expansion rule for the given formula.
    
    Args:
        formula: The formula to expand
        negated: Whether the formula is negated
    
    Returns:
        An expansion rule that can handle the formula, or None if no rule applies
    """
    for rule in get_all_expansion_rules():
        if rule.can_expand(formula, negated):
            return rule
    return None
