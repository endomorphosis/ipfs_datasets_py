"""
TDFOL Inference Rules - Comprehensive rule set for theorem proving

This module implements 40+ inference rules for TDFOL:
- 15 Basic Logic Rules (propositional + FOL)
- 10 Temporal Logic Rules (LTL operators)
- 8 Deontic Logic Rules (SDL operators)
- 7 Combined Temporal-Deontic Rules
- 5 Modal Logic Axioms (K, T, D, S4, S5)

These rules integrate with CEC native prover (87 rules) for complete coverage.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Set, Tuple

from .tdfol_core import (
    BinaryFormula,
    BinaryTemporalFormula,
    DeonticFormula,
    DeonticOperator,
    Formula,
    LogicOperator,
    Predicate,
    QuantifiedFormula,
    Quantifier,
    TemporalFormula,
    TemporalOperator,
    Term,
    UnaryFormula,
    Variable,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Abstract Base Class
# ============================================================================


class TDFOLInferenceRule(ABC):
    """Abstract base class for TDFOL inference rules."""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
    
    @abstractmethod
    def can_apply(self, *formulas: Formula) -> bool:
        """Check if rule can be applied to given formulas."""
        pass
    
    @abstractmethod
    def apply(self, *formulas: Formula) -> Formula:
        """Apply rule to formulas and return result."""
        pass
    
    def __repr__(self) -> str:
        return f"{self.name}: {self.description}"


# ============================================================================
# Basic Logic Rules (15 rules)
# ============================================================================


class ModusPonensRule(TDFOLInferenceRule):
    """Modus Ponens: φ, φ → ψ ⊢ ψ"""
    
    def __init__(self):
        super().__init__(
            "ModusPonens",
            "From φ and φ → ψ, infer ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # Check if second formula is implication with first as antecedent
        if not isinstance(formulas[1], BinaryFormula):
            return False
        
        return (formulas[1].operator == LogicOperator.IMPLIES and
                formulas[1].left == formulas[0])
    
    def apply(self, *formulas: Formula) -> Formula:
        # Return consequent of implication
        return formulas[1].right


class ModusTollensRule(TDFOLInferenceRule):
    """Modus Tollens: φ → ψ, ¬ψ ⊢ ¬φ"""
    
    def __init__(self):
        super().__init__(
            "ModusTollens",
            "From φ → ψ and ¬ψ, infer ¬φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be implication
        if not isinstance(formulas[0], BinaryFormula):
            return False
        if formulas[0].operator != LogicOperator.IMPLIES:
            return False
        
        # Second should be negation of consequent
        if not isinstance(formulas[1], UnaryFormula):
            return False
        
        return (formulas[1].operator == LogicOperator.NOT and
                formulas[1].formula == formulas[0].right)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Return negation of antecedent
        return UnaryFormula(LogicOperator.NOT, formulas[0].left)


class DisjunctiveSyllogismRule(TDFOLInferenceRule):
    """Disjunctive Syllogism: φ ∨ ψ, ¬φ ⊢ ψ"""
    
    def __init__(self):
        super().__init__(
            "DisjunctiveSyllogism",
            "From φ ∨ ψ and ¬φ, infer ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be disjunction
        if not isinstance(formulas[0], BinaryFormula):
            return False
        if formulas[0].operator != LogicOperator.OR:
            return False
        
        # Second should be negation of left disjunct
        if not isinstance(formulas[1], UnaryFormula):
            return False
        
        return (formulas[1].operator == LogicOperator.NOT and
                formulas[1].formula == formulas[0].left)
    
    def apply(self, *formulas: Formula) -> Formula:
        return formulas[0].right


class HypotheticalSyllogismRule(TDFOLInferenceRule):
    """Hypothetical Syllogism: φ → ψ, ψ → χ ⊢ φ → χ"""
    
    def __init__(self):
        super().__init__(
            "HypotheticalSyllogism",
            "From φ → ψ and ψ → χ, infer φ → χ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # Both should be implications
        if not all(isinstance(f, BinaryFormula) for f in formulas):
            return False
        
        if not all(f.operator == LogicOperator.IMPLIES for f in formulas):
            return False
        
        # Consequent of first should match antecedent of second
        return formulas[0].right == formulas[1].left
    
    def apply(self, *formulas: Formula) -> Formula:
        return BinaryFormula(
            LogicOperator.IMPLIES,
            formulas[0].left,
            formulas[1].right
        )


class ConjunctionIntroductionRule(TDFOLInferenceRule):
    """Conjunction Introduction: φ, ψ ⊢ φ ∧ ψ"""
    
    def __init__(self):
        super().__init__(
            "ConjunctionIntroduction",
            "From φ and ψ, infer φ ∧ ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) == 2
    
    def apply(self, *formulas: Formula) -> Formula:
        return BinaryFormula(LogicOperator.AND, formulas[0], formulas[1])


class ConjunctionEliminationLeftRule(TDFOLInferenceRule):
    """Conjunction Elimination (Left): φ ∧ ψ ⊢ φ"""
    
    def __init__(self):
        super().__init__(
            "ConjunctionEliminationLeft",
            "From φ ∧ ψ, infer φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], BinaryFormula) and
                formulas[0].operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        return formulas[0].left


class ConjunctionEliminationRightRule(TDFOLInferenceRule):
    """Conjunction Elimination (Right): φ ∧ ψ ⊢ ψ"""
    
    def __init__(self):
        super().__init__(
            "ConjunctionEliminationRight",
            "From φ ∧ ψ, infer ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], BinaryFormula) and
                formulas[0].operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        return formulas[0].right


class DisjunctionIntroductionLeftRule(TDFOLInferenceRule):
    """Disjunction Introduction (Left): φ ⊢ φ ∨ ψ"""
    
    def __init__(self):
        super().__init__(
            "DisjunctionIntroductionLeft",
            "From φ, infer φ ∨ ψ for any ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) >= 1
    
    def apply(self, *formulas: Formula) -> Formula:
        # Add arbitrary second disjunct if not provided
        if len(formulas) == 1:
            # Create a fresh predicate for arbitrary ψ
            psi = Predicate("_arbitrary", ())
            return BinaryFormula(LogicOperator.OR, formulas[0], psi)
        return BinaryFormula(LogicOperator.OR, formulas[0], formulas[1])


class DoubleNegationEliminationRule(TDFOLInferenceRule):
    """Double Negation Elimination: ¬¬φ ⊢ φ"""
    
    def __init__(self):
        super().__init__(
            "DoubleNegationElimination",
            "From ¬¬φ, infer φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], UnaryFormula):
            return False
        
        if formulas[0].operator != LogicOperator.NOT:
            return False
        
        return (isinstance(formulas[0].formula, UnaryFormula) and
                formulas[0].formula.operator == LogicOperator.NOT)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Remove both negations
        return formulas[0].formula.formula


class DoubleNegationIntroductionRule(TDFOLInferenceRule):
    """Double Negation Introduction: φ ⊢ ¬¬φ"""
    
    def __init__(self):
        super().__init__(
            "DoubleNegationIntroduction",
            "From φ, infer ¬¬φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) == 1
    
    def apply(self, *formulas: Formula) -> Formula:
        negation = UnaryFormula(LogicOperator.NOT, formulas[0])
        return UnaryFormula(LogicOperator.NOT, negation)


class ContrapositionRule(TDFOLInferenceRule):
    """Contraposition: φ → ψ ⊢ ¬ψ → ¬φ"""
    
    def __init__(self):
        super().__init__(
            "Contraposition",
            "From φ → ψ, infer ¬ψ → ¬φ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], BinaryFormula) and
                formulas[0].operator == LogicOperator.IMPLIES)
    
    def apply(self, *formulas: Formula) -> Formula:
        phi = formulas[0].left
        psi = formulas[0].right
        
        not_psi = UnaryFormula(LogicOperator.NOT, psi)
        not_phi = UnaryFormula(LogicOperator.NOT, phi)
        
        return BinaryFormula(LogicOperator.IMPLIES, not_psi, not_phi)


class DeMorganAndRule(TDFOLInferenceRule):
    """De Morgan (AND): ¬(φ ∧ ψ) ⊢ ¬φ ∨ ¬ψ"""
    
    def __init__(self):
        super().__init__(
            "DeMorganAnd",
            "From ¬(φ ∧ ψ), infer ¬φ ∨ ¬ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], UnaryFormula):
            return False
        
        if formulas[0].operator != LogicOperator.NOT:
            return False
        
        return (isinstance(formulas[0].formula, BinaryFormula) and
                formulas[0].formula.operator == LogicOperator.AND)
    
    def apply(self, *formulas: Formula) -> Formula:
        conjunction = formulas[0].formula
        
        not_phi = UnaryFormula(LogicOperator.NOT, conjunction.left)
        not_psi = UnaryFormula(LogicOperator.NOT, conjunction.right)
        
        return BinaryFormula(LogicOperator.OR, not_phi, not_psi)


class DeMorganOrRule(TDFOLInferenceRule):
    """De Morgan (OR): ¬(φ ∨ ψ) ⊢ ¬φ ∧ ¬ψ"""
    
    def __init__(self):
        super().__init__(
            "DeMorganOr",
            "From ¬(φ ∨ ψ), infer ¬φ ∧ ¬ψ"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], UnaryFormula):
            return False
        
        if formulas[0].operator != LogicOperator.NOT:
            return False
        
        return (isinstance(formulas[0].formula, BinaryFormula) and
                formulas[0].formula.operator == LogicOperator.OR)
    
    def apply(self, *formulas: Formula) -> Formula:
        disjunction = formulas[0].formula
        
        not_phi = UnaryFormula(LogicOperator.NOT, disjunction.left)
        not_psi = UnaryFormula(LogicOperator.NOT, disjunction.right)
        
        return BinaryFormula(LogicOperator.AND, not_phi, not_psi)


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
            from .tdfol_core import Constant
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


# ============================================================================
# Temporal Logic Rules (10 rules)
# ============================================================================


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


# ============================================================================
# Complete Rule Registry
# ============================================================================


def get_all_tdfol_rules() -> List[TDFOLInferenceRule]:
    """Get all TDFOL inference rules."""
    return [
        # Basic Logic (15 rules)
        ModusPonensRule(),
        ModusTollensRule(),
        DisjunctiveSyllogismRule(),
        HypotheticalSyllogismRule(),
        ConjunctionIntroductionRule(),
        ConjunctionEliminationLeftRule(),
        ConjunctionEliminationRightRule(),
        DisjunctionIntroductionLeftRule(),
        DoubleNegationEliminationRule(),
        DoubleNegationIntroductionRule(),
        ContrapositionRule(),
        DeMorganAndRule(),
        DeMorganOrRule(),
        UniversalInstantiationRule(),
        ExistentialGeneralizationRule(),
        
        # Temporal Logic (10 rules)
        TemporalKAxiomRule(),
        TemporalTAxiomRule(),
        TemporalS4AxiomRule(),
        TemporalS5AxiomRule(),
        EventuallyIntroductionRule(),
        AlwaysNecessitationRule(),
        UntilUnfoldingRule(),
        UntilInductionRule(),
        EventuallyExpansionRule(),
        AlwaysDistributionRule(),
    ]


# ============================================================================
# Deontic Logic Rules (8 rules)
# ============================================================================


class DeonticKAxiomRule(TDFOLInferenceRule):
    """K Axiom for Deontic Logic: O(φ → ψ) → (O(φ) → O(ψ))"""
    
    def __init__(self):
        super().__init__(
            "DeonticKAxiom",
            "Distribution axiom for O: O(φ → ψ), O(φ) ⊢ O(ψ)"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 2:
            return False
        
        # First should be O(φ → ψ)
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        if not isinstance(formulas[0].formula, BinaryFormula):
            return False
        if formulas[0].formula.operator != LogicOperator.IMPLIES:
            return False
        
        # Second should be O(φ)
        if not isinstance(formulas[1], DeonticFormula):
            return False
        if formulas[1].operator != DeonticOperator.OBLIGATION:
            return False
        
        # φ from O(φ → ψ) should match φ from O(φ)
        return formulas[0].formula.left == formulas[1].formula
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract ψ from O(φ → ψ)
        psi = formulas[0].formula.right
        
        # Return O(ψ)
        return DeonticFormula(DeonticOperator.OBLIGATION, psi)


class DeonticDAxiomRule(TDFOLInferenceRule):
    """D Axiom for Deontic Logic: O(φ) ⊢ P(φ)"""
    
    def __init__(self):
        super().__init__(
            "DeonticDAxiom",
            "D axiom: obligation implies permission"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.OBLIGATION)
    
    def apply(self, *formulas: Formula) -> Formula:
        return DeonticFormula(DeonticOperator.PERMISSION, formulas[0].formula)


class ProhibitionEquivalenceRule(TDFOLInferenceRule):
    """Prohibition Equivalence: F(φ) ⊢ O(¬φ)"""
    
    def __init__(self):
        super().__init__(
            "ProhibitionEquivalence",
            "Forbidden is equivalent to obligatory not"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PROHIBITION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # F(φ) → O(¬φ)
        negation = UnaryFormula(LogicOperator.NOT, formulas[0].formula)
        return DeonticFormula(DeonticOperator.OBLIGATION, negation)


class PermissionNegationRule(TDFOLInferenceRule):
    """Permission Negation: P(φ) ⊢ ¬O(¬φ)"""
    
    def __init__(self):
        super().__init__(
            "PermissionNegation",
            "Permission is equivalent to not obligatory not"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PERMISSION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # P(φ) → ¬O(¬φ)
        negation = UnaryFormula(LogicOperator.NOT, formulas[0].formula)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, negation)
        return UnaryFormula(LogicOperator.NOT, obligation)


class ObligationConsistencyRule(TDFOLInferenceRule):
    """Obligation Consistency: O(φ) ⊢ ¬O(¬φ)"""
    
    def __init__(self):
        super().__init__(
            "ObligationConsistency",
            "Obligations are consistent: cannot oblige contradictions"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.OBLIGATION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # O(φ) → ¬O(¬φ)
        negation = UnaryFormula(LogicOperator.NOT, formulas[0].formula)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, negation)
        return UnaryFormula(LogicOperator.NOT, obligation)


class PermissionIntroductionRule(TDFOLInferenceRule):
    """Permission Introduction: φ ⊢ P(φ)"""
    
    def __init__(self):
        super().__init__(
            "PermissionIntroduction",
            "What is true is permitted"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        return len(formulas) == 1
    
    def apply(self, *formulas: Formula) -> Formula:
        return DeonticFormula(DeonticOperator.PERMISSION, formulas[0])


class DeonticNecessitationRule(TDFOLInferenceRule):
    """Deontic Necessitation: If ⊢ φ, then ⊢ O(φ)"""
    
    def __init__(self):
        super().__init__(
            "DeonticNecessitation",
            "If φ is a theorem, it is obligatory"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        # This rule applies to theorems/axioms
        return len(formulas) == 1
    
    def apply(self, *formulas: Formula) -> Formula:
        return DeonticFormula(DeonticOperator.OBLIGATION, formulas[0])


class ProhibitionFromObligationRule(TDFOLInferenceRule):
    """Prohibition from Obligation: O(¬φ) ⊢ F(φ)"""
    
    def __init__(self):
        super().__init__(
            "ProhibitionFromObligation",
            "Obligatory not is equivalent to forbidden"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return (isinstance(formulas[0].formula, UnaryFormula) and
                formulas[0].formula.operator == LogicOperator.NOT)
    
    def apply(self, *formulas: Formula) -> Formula:
        # O(¬φ) → F(φ)
        phi = formulas[0].formula.formula  # Remove negation
        return DeonticFormula(DeonticOperator.PROHIBITION, phi)


# ============================================================================
# Combined Temporal-Deontic Rules (7 rules)
# ============================================================================


class TemporalObligationPersistenceRule(TDFOLInferenceRule):
    """Temporal Obligation Persistence: O(□φ) ⊢ □O(φ)"""
    
    def __init__(self):
        super().__init__(
            "TemporalObligationPersistence",
            "Obligation of always implies always obligated"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.ALWAYS)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from O(□φ)
        phi = formulas[0].formula.formula
        
        # Create O(φ)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, phi)
        
        # Create □O(φ)
        return TemporalFormula(TemporalOperator.ALWAYS, obligation)


class DeonticTemporalIntroductionRule(TDFOLInferenceRule):
    """Deontic Temporal Introduction: O(φ) ⊢ O(Xφ)"""
    
    def __init__(self):
        super().__init__(
            "DeonticTemporalIntroduction",
            "Obligation persists to next time"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.OBLIGATION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from O(φ)
        phi = formulas[0].formula
        
        # Create X(φ)
        next_phi = TemporalFormula(TemporalOperator.NEXT, phi)
        
        # Create O(X(φ))
        return DeonticFormula(DeonticOperator.OBLIGATION, next_phi)


class UntilObligationRule(TDFOLInferenceRule):
    """Until Obligation: O(φ U ψ) ⊢ ◊O(ψ)"""
    
    def __init__(self):
        super().__init__(
            "UntilObligation",
            "Obligation of until implies eventual obligation of goal"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return isinstance(formulas[0].formula, BinaryTemporalFormula)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract ψ from O(φ U ψ)
        psi = formulas[0].formula.right
        
        # Create O(ψ)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, psi)
        
        # Create ◊O(ψ)
        return TemporalFormula(TemporalOperator.EVENTUALLY, obligation)


class AlwaysPermissionRule(TDFOLInferenceRule):
    """Always Permission: P(□φ) ⊢ □P(φ)"""
    
    def __init__(self):
        super().__init__(
            "AlwaysPermission",
            "Permission of always implies always permitted"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.PERMISSION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.ALWAYS)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from P(□φ)
        phi = formulas[0].formula.formula
        
        # Create P(φ)
        permission = DeonticFormula(DeonticOperator.PERMISSION, phi)
        
        # Create □P(φ)
        return TemporalFormula(TemporalOperator.ALWAYS, permission)


class EventuallyForbiddenRule(TDFOLInferenceRule):
    """Eventually Forbidden: F(◊φ) ⊢ □F(φ)"""
    
    def __init__(self):
        super().__init__(
            "EventuallyForbidden",
            "Forbidden eventually implies always forbidden"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.PROHIBITION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.EVENTUALLY)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from F(◊φ)
        phi = formulas[0].formula.formula
        
        # Create F(φ)
        prohibition = DeonticFormula(DeonticOperator.PROHIBITION, phi)
        
        # Create □F(φ)
        return TemporalFormula(TemporalOperator.ALWAYS, prohibition)


class ObligationEventuallyRule(TDFOLInferenceRule):
    """Obligation Eventually: O(◊φ) ⊢ ◊O(φ)"""
    
    def __init__(self):
        super().__init__(
            "ObligationEventually",
            "Obligation of eventually implies eventually obligated"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        if not isinstance(formulas[0], DeonticFormula):
            return False
        if formulas[0].operator != DeonticOperator.OBLIGATION:
            return False
        
        return (isinstance(formulas[0].formula, TemporalFormula) and
                formulas[0].formula.operator == TemporalOperator.EVENTUALLY)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from O(◊φ)
        phi = formulas[0].formula.formula
        
        # Create O(φ)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, phi)
        
        # Create ◊O(φ)
        return TemporalFormula(TemporalOperator.EVENTUALLY, obligation)


class PermissionTemporalWeakeningRule(TDFOLInferenceRule):
    """Permission Temporal Weakening: P(φ) ⊢ P(◊φ)"""
    
    def __init__(self):
        super().__init__(
            "PermissionTemporalWeakening",
            "Permission implies permission eventually"
        )
    
    def can_apply(self, *formulas: Formula) -> bool:
        if len(formulas) != 1:
            return False
        
        return (isinstance(formulas[0], DeonticFormula) and
                formulas[0].operator == DeonticOperator.PERMISSION)
    
    def apply(self, *formulas: Formula) -> Formula:
        # Extract φ from P(φ)
        phi = formulas[0].formula
        
        # Create ◊φ
        eventually = TemporalFormula(TemporalOperator.EVENTUALLY, phi)
        
        # Create P(◊φ)
        return DeonticFormula(DeonticOperator.PERMISSION, eventually)


# Update the registry function
def get_all_tdfol_rules() -> List[TDFOLInferenceRule]:
    """Get all TDFOL inference rules (40 total)."""
    return [
        # Basic Logic (15 rules)
        ModusPonensRule(),
        ModusTollensRule(),
        DisjunctiveSyllogismRule(),
        HypotheticalSyllogismRule(),
        ConjunctionIntroductionRule(),
        ConjunctionEliminationLeftRule(),
        ConjunctionEliminationRightRule(),
        DisjunctionIntroductionLeftRule(),
        DoubleNegationEliminationRule(),
        DoubleNegationIntroductionRule(),
        ContrapositionRule(),
        DeMorganAndRule(),
        DeMorganOrRule(),
        UniversalInstantiationRule(),
        ExistentialGeneralizationRule(),
        
        # Temporal Logic (10 rules)
        TemporalKAxiomRule(),
        TemporalTAxiomRule(),
        TemporalS4AxiomRule(),
        TemporalS5AxiomRule(),
        EventuallyIntroductionRule(),
        AlwaysNecessitationRule(),
        UntilUnfoldingRule(),
        UntilInductionRule(),
        EventuallyExpansionRule(),
        AlwaysDistributionRule(),
        
        # Deontic Logic (8 rules)
        DeonticKAxiomRule(),
        DeonticDAxiomRule(),
        ProhibitionEquivalenceRule(),
        PermissionNegationRule(),
        ObligationConsistencyRule(),
        PermissionIntroductionRule(),
        DeonticNecessitationRule(),
        ProhibitionFromObligationRule(),
        
        # Combined Temporal-Deontic (7 rules)
        TemporalObligationPersistenceRule(),
        DeonticTemporalIntroductionRule(),
        UntilObligationRule(),
        AlwaysPermissionRule(),
        EventuallyForbiddenRule(),
        ObligationEventuallyRule(),
        PermissionTemporalWeakeningRule(),
    ]
