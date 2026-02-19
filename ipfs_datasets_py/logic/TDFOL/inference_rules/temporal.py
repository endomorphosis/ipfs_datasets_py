"""
Temporal Logic Inference Rules for TDFOL.

This module contains 20 Linear Temporal Logic (LTL) rules:
- Modal axioms (K, T, S4, S5)
- Always and Eventually operators
- Next, Until, Release operators
- Temporal induction rules
- Distribution and expansion rules
"""

from __future__ import annotations

from .base import TDFOLInferenceRule
from ..tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    Formula,
    LogicOperator,
    TemporalFormula,
    TemporalOperator,
    UnaryFormula,
)


class TemporalKAxiomRule(TDFOLInferenceRule):
    """K Axiom for Temporal Logic: □(φ → ψ) → (□φ → □ψ)"""
    
    def __init__(self):
        super().__init__(
            "TemporalKAxiom",
            "Distribution axiom for □: □(φ → ψ), □φ ⊢ □ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be □(φ → ψ)
        if not isinstance(formulas[0], TemporalFormula):
            return False
        if formulas[0].operator != TemporalOperator.ALWAYS:
            return False
        if not isinstance(formulas[0].formula, BinaryFormula):
            return False
        if formulas[0].formula.operator != LogicOperator.IMPLIES:
            return False
        
        # Second should be □φ
        if not isinstance(formulas[1], TemporalFormula):
            return False
        if formulas[1].operator != TemporalOperator.ALWAYS:
            return False
        
        # φ from □(φ → ψ) should match φ from □φ
        return formulas[0].formula.left == formulas[1].formula
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract ψ from □(φ → ψ)
        psi = formulas[0].formula.right
        
        # Return □ψ
        return TemporalFormula(TemporalOperator.ALWAYS, psi)


class TemporalTAxiomRule(TDFOLInferenceRule):
    """T Axiom for Temporal Logic: □φ ⊢ φ"""
    
    def __init__(self):
        super().__init__(
            "TemporalTAxiom",
            "Truth axiom: from □φ, infer φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], TemporalFormula) and
                formulas[0].operator == TemporalOperator.ALWAYS)
    
    def apply(self, *formulas: Formula) -> Formula:
        return formulas[0].formula


class TemporalS4AxiomRule(TDFOLInferenceRule):
    """S4 Axiom for Temporal Logic: □φ ⊢ □□φ"""
    
    def __init__(self):
        super().__init__(
            "TemporalS4Axiom",
            "Transitivity axiom: from □φ, infer □□φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], TemporalFormula) and
                formulas[0].operator == TemporalOperator.ALWAYS)
    
    def apply(self, *formulas: Formula) -> Formula:
        return TemporalFormula(TemporalOperator.ALWAYS, formulas[0])


class TemporalS5AxiomRule(TDFOLInferenceRule):
    """S5 Axiom for Temporal Logic: ◊φ ⊢ □◊φ"""
    
    def __init__(self):
        super().__init__(
            "TemporalS5Axiom",
            "Euclidean axiom: from ◊φ, infer □◊φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], TemporalFormula) and
                formulas[0].operator == TemporalOperator.EVENTUALLY)
    
    def apply(self, *formulas: Formula) -> Formula:
        return TemporalFormula(TemporalOperator.ALWAYS, formulas[0])


class EventuallyIntroductionRule(TDFOLInferenceRule):
    """Eventually Introduction: φ ⊢ ◊φ"""
    
    def __init__(self):
        super().__init__(
            "EventuallyIntroduction",
            "From φ, infer ◊φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) == 1
    
    def apply(self, *formulas: Formula) -> Formula:
        return TemporalFormula(TemporalOperator.EVENTUALLY, formulas[0])


class AlwaysNecessitationRule(TDFOLInferenceRule):
    """Always Necessitation: If ⊢ φ, then ⊢ □φ"""
    
    def __init__(self):
        super().__init__(
            "AlwaysNecessitation",
            "If φ is a theorem, infer □φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        # This rule applies to theorems/axioms
        return len(formulas) == 1
    
    def apply(self, *formulas: Formula) -> Formula:
        return TemporalFormula(TemporalOperator.ALWAYS, formulas[0])


class UntilUnfoldingRule(TDFOLInferenceRule):
    """Until Unfolding: φ U ψ ⊢ ψ ∨ (φ ∧ X(φ U ψ))"""
    
    def __init__(self):
        super().__init__(
            "UntilUnfolding",
            "Unfold until operator"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], BinaryTemporalFormula) and
                formulas[0].operator == TemporalOperator.UNTIL)
    
    def apply(self, *formulas: Formula) -> Formula:
        phi = formulas[0].left
        psi = formulas[0].right
        
        # X(φ U ψ)
        next_until = TemporalFormula(TemporalOperator.NEXT, formulas[0])
        
        # φ ∧ X(φ U ψ)
        conjunction = BinaryFormula(LogicOperator.AND, phi, next_until)
        
        # ψ ∨ (φ ∧ X(φ U ψ))
        return BinaryFormula(LogicOperator.OR, psi, conjunction)


class UntilInductionRule(TDFOLInferenceRule):
    """Until Induction: ψ ∨ (φ ∧ X(φ U ψ)) ⊢ φ U ψ"""
    
    def __init__(self):
        super().__init__(
            "UntilInduction",
            "Fold until operator"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        # Should be ψ ∨ (φ ∧ X(φ U ψ))
        if not isinstance(formulas[0], BinaryFormula):
            return False
        if formulas[0].operator != LogicOperator.OR:
            return False
        
        # Right side should be φ ∧ X(φ U ψ)
        right = formulas[0].right
        if not isinstance(right, BinaryFormula):
            return False
        if right.operator != LogicOperator.AND:
            return False
        
        # Right of that should be X(φ U ψ)
        if not isinstance(right.right, TemporalFormula):
            return False
        if right.right.operator != TemporalOperator.NEXT:
            return False
        
        return isinstance(right.right.formula, BinaryTemporalFormula)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ U ψ from X(φ U ψ)
        return formulas[0].right.right.formula


class EventuallyExpansionRule(TDFOLInferenceRule):
    """Eventually Expansion: ◊φ ⊢ φ ∨ X◊φ"""
    
    def __init__(self):
        super().__init__(
            "EventuallyExpansion",
            "Expand eventually operator"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], TemporalFormula) and
                formulas[0].operator == TemporalOperator.EVENTUALLY)
    
    def apply(self, *formulas: Formula) -> Formula:
        phi = formulas[0].formula
        
        # X◊φ
        next_eventually = TemporalFormula(TemporalOperator.NEXT, formulas[0])
        
        # φ ∨ X◊φ
        return BinaryFormula(LogicOperator.OR, phi, next_eventually)


class AlwaysDistributionRule(TDFOLInferenceRule):
    """Always Distribution: □(φ ∧ ψ) ⊢ □φ ∧ □ψ"""
    
    def __init__(self):
        super().__init__(
            "AlwaysDistribution",
            "Distribute □ over ∧"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], TemporalFormula):
            return False
        if formulas[0].operator != TemporalOperator.ALWAYS:
            return False
        
        return (isinstance(formulas[0].formula, BinaryFormula) and
                formulas[0].formula.operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        conjunction = formulas[0].formula
        
        always_phi = TemporalFormula(TemporalOperator.ALWAYS, conjunction.left)
        always_psi = TemporalFormula(TemporalOperator.ALWAYS, conjunction.right)
        
        return BinaryFormula(LogicOperator.AND, always_phi, always_psi)


class AlwaysEventuallyExpansionRule(TDFOLInferenceRule):
    """Always-Eventually Expansion: □◊φ ⊢ ◊φ ∧ □◊φ"""
    
    def __init__(self):
        super().__init__(
            "AlwaysEventuallyExpansion",
            "From □◊φ, infer ◊φ and maintain □◊φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        # Check for □◊φ pattern
        if not isinstance(formulas[0], TemporalFormula):
            return False
        if formulas[0].operator != TemporalOperator.ALWAYS:
            return False
        
        inner = formulas[0].formula
        return (isinstance(inner, TemporalFormula) and
                inner.operator == TemporalOperator.EVENTUALLY)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract ◊φ from □◊φ
        eventually_phi = formulas[0].formula
        
        # Return ◊φ (can infer eventually from always-eventually)
        return eventually_phi


class EventuallyAlwaysContractionRule(TDFOLInferenceRule):
    """Eventually-Always Contraction: ◊□φ, φ ⊢ □φ"""
    
    def __init__(self):
        super().__init__(
            "EventuallyAlwaysContraction",
            "From ◊□φ and φ, infer □φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be ◊□φ
        if not isinstance(formulas[0], TemporalFormula):
            return False
        if formulas[0].operator != TemporalOperator.EVENTUALLY:
            return False
        
        inner = formulas[0].formula
        if not isinstance(inner, TemporalFormula):
            return False
        if inner.operator != TemporalOperator.ALWAYS:
            return False
        
        # φ from □φ should match second formula
        return inner.formula == formulas[1]
    
    def apply(self, *formulas: Formula) -> Formula:
        # Return □φ
        return formulas[0].formula


class UntilReleaseDualityRule(TDFOLInferenceRule):
    """Until-Release Duality: φ U ψ ⊢ ¬(¬φ R ¬ψ)"""
    
    def __init__(self):
        super().__init__(
            "UntilReleaseDuality",
            "Until-Release duality: φ U ψ ↔ ¬(¬φ R ¬ψ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        return (isinstance(formulas[0], BinaryTemporalFormula) and
                formulas[0].operator == TemporalOperator.UNTIL)
    
    def apply(self, *formulas: Formula) -> Formula:
        until_formula = formulas[0]
        phi = until_formula.left
        psi = until_formula.right
        
        # Create ¬φ and ¬ψ
        not_phi = UnaryFormula(LogicOperator.NOT, phi)
        not_psi = UnaryFormula(LogicOperator.NOT, psi)
        
        # Create ¬φ R ¬ψ
        release = BinaryTemporalFormula(TemporalOperator.RELEASE, not_phi, not_psi)
        
        # Return ¬(¬φ R ¬ψ)
        return UnaryFormula(LogicOperator.NOT, release)


class WeakUntilExpansionRule(TDFOLInferenceRule):
    """Weak Until Expansion: φ W ψ ⊢ (φ U ψ) ∨ □φ"""
    
    def __init__(self):
        super().__init__(
            "WeakUntilExpansion",
            "Weak until expands to: φ W ψ ↔ (φ U ψ) ∨ □φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        return (isinstance(formulas[0], BinaryTemporalFormula) and
                formulas[0].operator == TemporalOperator.WEAK_UNTIL)
    
    def apply(self, *formulas: Formula) -> Formula:
        weak_until = formulas[0]
        phi = weak_until.left
        psi = weak_until.right
        
        # Create φ U ψ
        until = BinaryTemporalFormula(TemporalOperator.UNTIL, phi, psi)
        
        # Create □φ
        always_phi = TemporalFormula(TemporalOperator.ALWAYS, phi)
        
        # Return (φ U ψ) ∨ □φ
        return BinaryFormula(LogicOperator.OR, until, always_phi)


class NextDistributionRule(TDFOLInferenceRule):
    """Next Distribution: X(φ ∧ ψ) ⊢ Xφ ∧ Xψ"""
    
    def __init__(self):
        super().__init__(
            "NextDistribution",
            "Next distributes over conjunction: X(φ ∧ ψ) ↔ Xφ ∧ Xψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        if not isinstance(formulas[0], TemporalFormula):
            return False
        if formulas[0].operator != TemporalOperator.NEXT:
            return False
        
        return (isinstance(formulas[0].formula, BinaryFormula) and
                formulas[0].formula.operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        next_formula = formulas[0]
        conjunction = next_formula.formula
        
        phi = conjunction.left
        psi = conjunction.right
        
        # Create Xφ and Xψ
        next_phi = TemporalFormula(TemporalOperator.NEXT, phi)
        next_psi = TemporalFormula(TemporalOperator.NEXT, psi)
        
        # Return Xφ ∧ Xψ
        return BinaryFormula(LogicOperator.AND, next_phi, next_psi)


class EventuallyAggregationRule(TDFOLInferenceRule):
    """Eventually Aggregation: ◊φ ∨ ◊ψ ⊢ ◊(φ ∨ ψ)"""
    
    def __init__(self):
        super().__init__(
            "EventuallyAggregation",
            "Eventually aggregates disjunction: ◊φ ∨ ◊ψ → ◊(φ ∨ ψ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        if not isinstance(formulas[0], BinaryFormula):
            return False
        if formulas[0].operator != LogicOperator.OR:
            return False
        
        left = formulas[0].left
        right = formulas[0].right
        
        return (isinstance(left, TemporalFormula) and
                left.operator == TemporalOperator.EVENTUALLY and
                isinstance(right, TemporalFormula) and
                right.operator == TemporalOperator.EVENTUALLY)
    
    def apply(self, *formulas: Formula) -> Formula:
        disjunction = formulas[0]
        eventually_phi = disjunction.left
        eventually_psi = disjunction.right
        
        phi = eventually_phi.formula
        psi = eventually_psi.formula
        
        # Create φ ∨ ψ
        phi_or_psi = BinaryFormula(LogicOperator.OR, phi, psi)
        
        # Return ◊(φ ∨ ψ)
        return TemporalFormula(TemporalOperator.EVENTUALLY, phi_or_psi)


class TemporalInductionRule(TDFOLInferenceRule):
    """Temporal Induction: □(φ → Xφ), φ ⊢ □φ"""
    
    def __init__(self):
        super().__init__(
            "TemporalInduction",
            "From □(φ → Xφ) and φ, infer □φ (temporal induction)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be □(φ → Xφ)
        if not isinstance(formulas[0], TemporalFormula):
            return False
        if formulas[0].operator != TemporalOperator.ALWAYS:
            return False
        
        inner = formulas[0].formula
        if not isinstance(inner, BinaryFormula):
            return False
        if inner.operator != LogicOperator.IMPLIES:
            return False
        
        # Right side of implication should be Xφ
        if not isinstance(inner.right, TemporalFormula):
            return False
        if inner.right.operator != TemporalOperator.NEXT:
            return False
        
        # φ from both places should match second formula
        phi_left = inner.left
        phi_right = inner.right.formula
        
        return phi_left == phi_right == formulas[1]
    
    def apply(self, *formulas: Formula) -> Formula:
        phi = formulas[1]
        
        # Return □φ (by induction)
        return TemporalFormula(TemporalOperator.ALWAYS, phi)


class UntilInductionStepRule(TDFOLInferenceRule):
    """Until Induction Step: φ U ψ ⊢ ψ ∨ (φ ∧ X(φ U ψ))"""
    
    def __init__(self):
        super().__init__(
            "UntilInductionStep",
            "Until induction: (φ U ψ) → ψ ∨ (φ ∧ X(φ U ψ))"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        return (isinstance(formulas[0], BinaryTemporalFormula) and
                formulas[0].operator == TemporalOperator.UNTIL)
    
    def apply(self, *formulas: Formula) -> Formula:
        until_formula = formulas[0]
        phi = until_formula.left
        psi = until_formula.right
        
        # Create X(φ U ψ)
        next_until = TemporalFormula(TemporalOperator.NEXT, until_formula)
        
        # Create φ ∧ X(φ U ψ)
        phi_and_next = BinaryFormula(LogicOperator.AND, phi, next_until)
        
        # Return ψ ∨ (φ ∧ X(φ U ψ))
        return BinaryFormula(LogicOperator.OR, psi, phi_and_next)


class ReleaseCoinductionRule(TDFOLInferenceRule):
    """Release Coinduction: φ R ψ ⊢ ψ ∧ (φ ∨ X(φ R ψ))"""
    
    def __init__(self):
        super().__init__(
            "ReleaseCoinduction",
            "Release coinduction: (φ R ψ) ↔ ψ ∧ (φ ∨ X(φ R ψ))"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        return (isinstance(formulas[0], BinaryTemporalFormula) and
                formulas[0].operator == TemporalOperator.RELEASE)
    
    def apply(self, *formulas: Formula) -> Formula:
        release_formula = formulas[0]
        phi = release_formula.left
        psi = release_formula.right
        
        # Create X(φ R ψ)
        next_release = TemporalFormula(TemporalOperator.NEXT, release_formula)
        
        # Create φ ∨ X(φ R ψ)
        phi_or_next = BinaryFormula(LogicOperator.OR, phi, next_release)
        
        # Return ψ ∧ (φ ∨ X(φ R ψ))
        return BinaryFormula(LogicOperator.AND, psi, phi_or_next)


class EventuallyDistributionRule(TDFOLInferenceRule):
    """Eventually Distribution: ◊(φ ∧ ψ) ⊢ ◊φ ∧ ◊ψ is INVALID, but reverse is"""
    
    def __init__(self):
        super().__init__(
            "EventuallyDistribution",
            "Eventually weakening: ◊(φ ∧ ψ) → ◊φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) < 1:
            return False
        
        if not isinstance(formulas[0], TemporalFormula):
            return False
        if formulas[0].operator != TemporalOperator.EVENTUALLY:
            return False
        
        return (isinstance(formulas[0].formula, BinaryFormula) and
                formulas[0].formula.operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        eventually_formula = formulas[0]
        conjunction = eventually_formula.formula
        
        phi = conjunction.left
        
        # Return ◊φ (weaken by dropping ψ)
        return TemporalFormula(TemporalOperator.EVENTUALLY, phi)



# Export all rules
__all__ = [
    'TemporalKAxiomRule',
    'TemporalTAxiomRule',
    'TemporalS4AxiomRule',
    'TemporalS5AxiomRule',
    'EventuallyIntroductionRule',
    'AlwaysNecessitationRule',
    'UntilUnfoldingRule',
    'UntilInductionRule',
    'EventuallyExpansionRule',
    'AlwaysDistributionRule',
    'AlwaysEventuallyExpansionRule',
    'EventuallyAlwaysContractionRule',
    'UntilReleaseDualityRule',
    'WeakUntilExpansionRule',
    'NextDistributionRule',
    'EventuallyAggregationRule',
    'TemporalInductionRule',
    'UntilInductionStepRule',
    'ReleaseCoinductionRule',
    'EventuallyDistributionRule',
]
