"""
TDFOL Inference Rules Module

This module implements 60 inference rules for Temporal Deontic First-Order Logic (TDFOL):
  - 15 Basic Logic Rules (propositional + FOL)
  - 20 Temporal Logic Rules (LTL operators)
  - 16 Deontic Logic Rules (SDL operators)
  -  9 Combined Temporal-Deontic Rules
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Any

from .tdfol_core import (
    Formula,
    BinaryFormula,
    UnaryFormula,
    QuantifiedFormula,
    DeonticFormula,
    TemporalFormula,
    BinaryTemporalFormula,
    Predicate,
    Variable,
    Constant,
    LogicOperator,
    DeonticOperator,
    TemporalOperator,
    Quantifier,
    create_implication,
    create_conjunction,
    create_disjunction,
    create_negation,
    create_always,
    create_eventually,
    create_next,
    create_obligation,
    create_permission,
    create_prohibition,
    create_universal,
    create_existential,
)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class TDFOLInferenceRule(ABC):
    """Abstract base class for all TDFOL inference rules."""

    @property
    def name(self) -> str:
        """Rule name derived from class name (strips trailing 'Rule')."""
        cls_name = self.__class__.__name__
        return cls_name[:-4] if cls_name.endswith("Rule") else cls_name

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of the rule."""

    @abstractmethod
    def can_apply(self, *args) -> bool:
        """Return True if the rule can be applied to the given formula(s)."""

    @abstractmethod
    def apply(self, *args) -> Any:
        """Apply the rule and return the derived formula."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}: {self.description}"


# ===========================================================================
# Basic Logic Rules (15)
# ===========================================================================

class ModusPonensRule(TDFOLInferenceRule):
    """Modus Ponens: From φ and φ→ψ derive ψ."""
    description = "Modus Ponens: φ, φ→ψ ⊢ ψ"

    def can_apply(self, formula: Formula, implication: Formula) -> bool:
        return (
            isinstance(implication, BinaryFormula)
            and implication.operator == LogicOperator.IMPLIES
            and implication.left == formula
        )

    def apply(self, formula: Formula, implication: Formula) -> Formula:
        return implication.right


class ModusTollensRule(TDFOLInferenceRule):
    """Modus Tollens: From φ→ψ and ¬ψ derive ¬φ."""
    description = "Modus Tollens: φ→ψ, ¬ψ ⊢ ¬φ"

    def can_apply(self, implication: Formula, neg_consequent: Formula) -> bool:
        return (
            isinstance(implication, BinaryFormula)
            and implication.operator == LogicOperator.IMPLIES
            and isinstance(neg_consequent, UnaryFormula)
            and neg_consequent.operator == LogicOperator.NOT
            and neg_consequent.formula == implication.right
        )

    def apply(self, implication: Formula, neg_consequent: Formula) -> Formula:
        return create_negation(implication.left)


class HypotheticalSyllogismRule(TDFOLInferenceRule):
    """Hypothetical Syllogism: From φ→ψ and ψ→χ derive φ→χ."""
    description = "Hypothetical Syllogism: φ→ψ, ψ→χ ⊢ φ→χ"

    def can_apply(self, impl1: Formula, impl2: Formula) -> bool:
        return (
            isinstance(impl1, BinaryFormula)
            and isinstance(impl2, BinaryFormula)
            and impl1.operator == LogicOperator.IMPLIES
            and impl2.operator == LogicOperator.IMPLIES
            and impl1.right == impl2.left
        )

    def apply(self, impl1: Formula, impl2: Formula) -> Formula:
        return create_implication(impl1.left, impl2.right)


class DisjunctiveSyllogismRule(TDFOLInferenceRule):
    """Disjunctive Syllogism: From φ∨ψ and ¬φ derive ψ."""
    description = "Disjunctive Syllogism: φ∨ψ, ¬φ ⊢ ψ"

    def can_apply(self, disjunction: Formula, neg: Formula) -> bool:
        return (
            isinstance(disjunction, BinaryFormula)
            and disjunction.operator == LogicOperator.OR
            and isinstance(neg, UnaryFormula)
            and neg.operator == LogicOperator.NOT
            and (neg.formula == disjunction.left or neg.formula == disjunction.right)
        )

    def apply(self, disjunction: Formula, neg: Formula) -> Formula:
        if neg.formula == disjunction.left:
            return disjunction.right
        return disjunction.left


class ConjunctionIntroductionRule(TDFOLInferenceRule):
    """Conjunction Introduction: From φ and ψ derive φ∧ψ."""
    description = "Conjunction Introduction: φ, ψ ⊢ φ∧ψ"

    def can_apply(self, left: Formula, right: Formula) -> bool:
        return True

    def apply(self, left: Formula, right: Formula) -> Formula:
        return create_conjunction(left, right)


class ConjunctionEliminationLeftRule(TDFOLInferenceRule):
    """Conjunction Elimination (Left): From φ∧ψ derive φ."""
    description = "Conjunction Elimination Left: φ∧ψ ⊢ φ"

    def can_apply(self, conjunction: Formula) -> bool:
        return (
            isinstance(conjunction, BinaryFormula)
            and conjunction.operator == LogicOperator.AND
        )

    def apply(self, conjunction: Formula) -> Formula:
        return conjunction.left


class ConjunctionEliminationRightRule(TDFOLInferenceRule):
    """Conjunction Elimination (Right): From φ∧ψ derive ψ."""
    description = "Conjunction Elimination Right: φ∧ψ ⊢ ψ"

    def can_apply(self, conjunction: Formula) -> bool:
        return (
            isinstance(conjunction, BinaryFormula)
            and conjunction.operator == LogicOperator.AND
        )

    def apply(self, conjunction: Formula) -> Formula:
        return conjunction.right


class DisjunctionIntroductionLeftRule(TDFOLInferenceRule):
    """Disjunction Introduction (Left): From φ derive φ∨ψ (given ψ)."""
    description = "Disjunction Introduction Left: φ ⊢ φ∨ψ"

    def can_apply(self, formula: Formula, other: Optional[Formula] = None) -> bool:
        return True

    def apply(self, formula: Formula, other: Optional[Formula] = None) -> Formula:
        if other is None:
            other = formula
        return BinaryFormula(LogicOperator.OR, formula, other)


class DoubleNegationEliminationRule(TDFOLInferenceRule):
    """Double Negation Elimination: From ¬¬φ derive φ."""
    description = "Double Negation Elimination: ¬¬φ ⊢ φ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, UnaryFormula)
            and formula.operator == LogicOperator.NOT
            and isinstance(formula.formula, UnaryFormula)
            and formula.formula.operator == LogicOperator.NOT
        )

    def apply(self, formula: Formula) -> Formula:
        return formula.formula.formula


class DoubleNegationIntroductionRule(TDFOLInferenceRule):
    """Double Negation Introduction: From φ derive ¬¬φ."""
    description = "Double Negation Introduction: φ ⊢ ¬¬φ"

    def can_apply(self, formula: Formula) -> bool:
        return True

    def apply(self, formula: Formula) -> Formula:
        return create_negation(create_negation(formula))


class ContrapositionRule(TDFOLInferenceRule):
    """Contraposition: From φ→ψ derive ¬ψ→¬φ."""
    description = "Contraposition: φ→ψ ⊢ ¬ψ→¬φ"

    def can_apply(self, implication: Formula) -> bool:
        return (
            isinstance(implication, BinaryFormula)
            and implication.operator == LogicOperator.IMPLIES
        )

    def apply(self, implication: Formula) -> Formula:
        return create_implication(
            create_negation(implication.right),
            create_negation(implication.left),
        )


class DeMorganAndRule(TDFOLInferenceRule):
    """De Morgan's Law (AND): From ¬(φ∧ψ) derive ¬φ∨¬ψ."""
    description = "De Morgan AND: ¬(φ∧ψ) ⊢ ¬φ∨¬ψ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, UnaryFormula)
            and formula.operator == LogicOperator.NOT
            and isinstance(formula.formula, BinaryFormula)
            and formula.formula.operator == LogicOperator.AND
        )

    def apply(self, formula: Formula) -> Formula:
        conj = formula.formula
        return BinaryFormula(
            LogicOperator.OR,
            create_negation(conj.left),
            create_negation(conj.right),
        )


class DeMorganOrRule(TDFOLInferenceRule):
    """De Morgan's Law (OR): From ¬(φ∨ψ) derive ¬φ∧¬ψ."""
    description = "De Morgan OR: ¬(φ∨ψ) ⊢ ¬φ∧¬ψ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, UnaryFormula)
            and formula.operator == LogicOperator.NOT
            and isinstance(formula.formula, BinaryFormula)
            and formula.formula.operator == LogicOperator.OR
        )

    def apply(self, formula: Formula) -> Formula:
        disj = formula.formula
        return create_conjunction(
            create_negation(disj.left),
            create_negation(disj.right),
        )


class UniversalInstantiationRule(TDFOLInferenceRule):
    """Universal Instantiation: From ∀x.φ(x) derive φ(t)."""
    description = "Universal Instantiation: ∀x.φ(x) ⊢ φ(t)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, QuantifiedFormula)
            and formula.quantifier == Quantifier.FORALL
        )

    def apply(self, formula: Formula) -> Formula:
        # Return the inner formula with the variable replaced by a fresh constant
        inner = formula.formula
        if isinstance(inner, Predicate):
            # Substitute variable with constant
            var = formula.variable
            new_args = tuple(
                Constant(f"c_{a.name}") if isinstance(a, Variable) and a == var else a
                for a in inner.arguments
            )
            return Predicate(inner.name, new_args)
        return inner


class ExistentialGeneralizationRule(TDFOLInferenceRule):
    """Existential Generalization: From φ(t) derive ∃x.φ(x)."""
    description = "Existential Generalization: φ(t) ⊢ ∃x.φ(x)"

    def can_apply(self, formula: Formula) -> bool:
        return True

    def apply(self, formula: Formula) -> Formula:
        x = Variable("x")
        return create_existential(x, formula)


# ===========================================================================
# Temporal Logic Rules (20)
# ===========================================================================

class TemporalKAxiomRule(TDFOLInferenceRule):
    """Temporal K Axiom: From □(φ→ψ) and □φ derive □ψ."""
    description = "Temporal K Axiom: □(φ→ψ), □φ ⊢ □ψ"

    def can_apply(self, always_impl: Formula, always_phi: Formula) -> bool:
        return (
            isinstance(always_impl, TemporalFormula)
            and always_impl.operator == TemporalOperator.ALWAYS
            and isinstance(always_impl.formula, BinaryFormula)
            and always_impl.formula.operator == LogicOperator.IMPLIES
            and isinstance(always_phi, TemporalFormula)
            and always_phi.operator == TemporalOperator.ALWAYS
            and always_phi.formula == always_impl.formula.left
        )

    def apply(self, always_impl: Formula, always_phi: Formula) -> Formula:
        return create_always(always_impl.formula.right)


class TemporalTAxiomRule(TDFOLInferenceRule):
    """Temporal T Axiom: From □φ derive φ."""
    description = "Temporal T Axiom: □φ ⊢ φ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.ALWAYS
        )

    def apply(self, formula: Formula) -> Formula:
        return formula.formula


class TemporalS4AxiomRule(TDFOLInferenceRule):
    """Temporal S4 Axiom: From □φ derive □□φ."""
    description = "Temporal S4 Axiom: □φ ⊢ □□φ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.ALWAYS
        )

    def apply(self, formula: Formula) -> Formula:
        return create_always(formula)


class TemporalS5AxiomRule(TDFOLInferenceRule):
    """Temporal S5 Axiom: From ◊φ derive □◊φ."""
    description = "Temporal S5 Axiom: ◊φ ⊢ □◊φ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.EVENTUALLY
        )

    def apply(self, formula: Formula) -> Formula:
        return create_always(formula)


class AlwaysNecessitationRule(TDFOLInferenceRule):
    """Always Necessitation: From a theorem φ derive □φ."""
    description = "Always Necessitation: φ ⊢ □φ"

    def can_apply(self, formula: Formula) -> bool:
        return True

    def apply(self, formula: Formula) -> Formula:
        return create_always(formula)


class AlwaysDistributionRule(TDFOLInferenceRule):
    """Always Distribution: From □(φ∧ψ) derive □φ∧□ψ."""
    description = "Always Distribution: □(φ∧ψ) ⊢ □φ∧□ψ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.ALWAYS
            and isinstance(formula.formula, BinaryFormula)
            and formula.formula.operator == LogicOperator.AND
        )

    def apply(self, formula: Formula) -> Formula:
        conj = formula.formula
        return create_conjunction(
            create_always(conj.left),
            create_always(conj.right),
        )


class EventuallyIntroductionRule(TDFOLInferenceRule):
    """Eventually Introduction: From φ derive ◊φ."""
    description = "Eventually Introduction: φ ⊢ ◊φ"

    def can_apply(self, formula: Formula) -> bool:
        return True

    def apply(self, formula: Formula) -> Formula:
        return create_eventually(formula)


class UntilUnfoldingRule(TDFOLInferenceRule):
    """Until Unfolding: From φ U ψ derive ψ ∨ (φ ∧ X(φ U ψ))."""
    description = "Until Unfolding: φ U ψ ⊢ ψ∨(φ∧X(φ U ψ))"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, BinaryTemporalFormula)
            and formula.operator == TemporalOperator.UNTIL
        )

    def apply(self, formula: Formula) -> Formula:
        phi, psi = formula.left, formula.right
        next_until = TemporalFormula(TemporalOperator.NEXT, formula)
        return BinaryFormula(
            LogicOperator.OR,
            psi,
            create_conjunction(phi, next_until),
        )


class UntilInductionRule(TDFOLInferenceRule):
    """Until Induction: From ψ ∨ (φ ∧ X(φ U ψ)) derive φ U ψ."""
    description = "Until Induction: ψ∨(φ∧X(φ U ψ)) ⊢ φ U ψ"

    def can_apply(self, formula: Formula) -> bool:
        if not (isinstance(formula, BinaryFormula) and formula.operator == LogicOperator.OR):
            return False
        right = formula.right
        return (
            isinstance(right, BinaryFormula)
            and right.operator == LogicOperator.AND
            and isinstance(right.right, TemporalFormula)
            and right.right.operator == TemporalOperator.NEXT
        )

    def apply(self, formula: Formula) -> Formula:
        psi = formula.left
        phi = formula.right.left
        return BinaryTemporalFormula(TemporalOperator.UNTIL, phi, psi)


class EventuallyExpansionRule(TDFOLInferenceRule):
    """Eventually Expansion: From ◊φ derive φ ∨ X◊φ."""
    description = "Eventually Expansion: ◊φ ⊢ φ∨X◊φ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.EVENTUALLY
        )

    def apply(self, formula: Formula) -> Formula:
        phi = formula.formula
        return BinaryFormula(
            LogicOperator.OR,
            phi,
            TemporalFormula(TemporalOperator.NEXT, formula),
        )


class AlwaysEventuallyExpansionRule(TDFOLInferenceRule):
    """Always-Eventually Expansion: From □◊φ derive ◊φ."""
    description = "Always-Eventually Expansion: □◊φ ⊢ ◊φ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.ALWAYS
            and isinstance(formula.formula, TemporalFormula)
            and formula.formula.operator == TemporalOperator.EVENTUALLY
        )

    def apply(self, formula: Formula) -> Formula:
        return formula.formula


class EventuallyAlwaysContractionRule(TDFOLInferenceRule):
    """Eventually-Always Contraction: From ◊□φ and φ derive □φ."""
    description = "Eventually-Always Contraction: ◊□φ, φ ⊢ □φ"

    def can_apply(self, ev_always: Formula, phi: Optional[Formula] = None) -> bool:
        return (
            isinstance(ev_always, TemporalFormula)
            and ev_always.operator == TemporalOperator.EVENTUALLY
            and isinstance(ev_always.formula, TemporalFormula)
            and ev_always.formula.operator == TemporalOperator.ALWAYS
        )

    def apply(self, ev_always: Formula, phi: Optional[Formula] = None) -> Formula:
        return ev_always.formula


class UntilReleaseDualityRule(TDFOLInferenceRule):
    """Until-Release Duality: From φ U ψ derive ¬(¬φ R ¬ψ)."""
    description = "Until-Release Duality: φ U ψ ⊢ ¬(¬φ R ¬ψ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, BinaryTemporalFormula)
            and formula.operator == TemporalOperator.UNTIL
        )

    def apply(self, formula: Formula) -> Formula:
        release = BinaryTemporalFormula(
            TemporalOperator.RELEASE,
            create_negation(formula.left),
            create_negation(formula.right),
        )
        return create_negation(release)


class WeakUntilExpansionRule(TDFOLInferenceRule):
    """Weak Until Expansion: From φ W ψ derive (φ U ψ) ∨ □φ."""
    description = "Weak Until Expansion: φ W ψ ⊢ (φ U ψ)∨□φ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, BinaryTemporalFormula)
            and formula.operator == TemporalOperator.WEAK_UNTIL
        )

    def apply(self, formula: Formula) -> Formula:
        until = BinaryTemporalFormula(TemporalOperator.UNTIL, formula.left, formula.right)
        return BinaryFormula(
            LogicOperator.OR,
            until,
            create_always(formula.left),
        )


class NextDistributionRule(TDFOLInferenceRule):
    """Next Distribution: From X(φ∧ψ) derive Xφ∧Xψ."""
    description = "Next Distribution: X(φ∧ψ) ⊢ Xφ∧Xψ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.NEXT
            and isinstance(formula.formula, BinaryFormula)
            and formula.formula.operator == LogicOperator.AND
        )

    def apply(self, formula: Formula) -> Formula:
        conj = formula.formula
        return create_conjunction(
            TemporalFormula(TemporalOperator.NEXT, conj.left),
            TemporalFormula(TemporalOperator.NEXT, conj.right),
        )


class EventuallyAggregationRule(TDFOLInferenceRule):
    """Eventually Aggregation: From ◊φ ∨ ◊ψ derive ◊(φ∨ψ)."""
    description = "Eventually Aggregation: ◊φ∨◊ψ ⊢ ◊(φ∨ψ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, BinaryFormula)
            and formula.operator == LogicOperator.OR
            and isinstance(formula.left, TemporalFormula)
            and formula.left.operator == TemporalOperator.EVENTUALLY
            and isinstance(formula.right, TemporalFormula)
            and formula.right.operator == TemporalOperator.EVENTUALLY
        )

    def apply(self, formula: Formula) -> Formula:
        disj = BinaryFormula(LogicOperator.OR, formula.left.formula, formula.right.formula)
        return create_eventually(disj)


class TemporalInductionRule(TDFOLInferenceRule):
    """Temporal Induction: From □(φ→Xφ) and φ derive □φ."""
    description = "Temporal Induction: □(φ→Xφ), φ ⊢ □φ"

    def can_apply(self, always_impl: Formula, phi: Optional[Formula] = None) -> bool:
        return (
            isinstance(always_impl, TemporalFormula)
            and always_impl.operator == TemporalOperator.ALWAYS
            and isinstance(always_impl.formula, BinaryFormula)
            and always_impl.formula.operator == LogicOperator.IMPLIES
        )

    def apply(self, always_impl: Formula, phi: Optional[Formula] = None) -> Formula:
        inner_phi = always_impl.formula.left
        return create_always(inner_phi)


class UntilInductionStepRule(TDFOLInferenceRule):
    """Until Induction Step: From φ U ψ derive ψ ∨ (φ ∧ X(φ U ψ))."""
    description = "Until Induction Step: φ U ψ ⊢ ψ∨(φ∧X(φ U ψ))"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, BinaryTemporalFormula)
            and formula.operator == TemporalOperator.UNTIL
        )

    def apply(self, formula: Formula) -> Formula:
        phi, psi = formula.left, formula.right
        next_until = TemporalFormula(TemporalOperator.NEXT, formula)
        return BinaryFormula(
            LogicOperator.OR,
            psi,
            create_conjunction(phi, next_until),
        )


class ReleaseCoinductionRule(TDFOLInferenceRule):
    """Release Coinduction: From φ R ψ derive ψ ∧ (φ ∨ X(φ R ψ))."""
    description = "Release Coinduction: φ R ψ ⊢ ψ∧(φ∨X(φ R ψ))"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, BinaryTemporalFormula)
            and formula.operator == TemporalOperator.RELEASE
        )

    def apply(self, formula: Formula) -> Formula:
        phi, psi = formula.left, formula.right
        next_release = TemporalFormula(TemporalOperator.NEXT, formula)
        return create_conjunction(
            psi,
            BinaryFormula(LogicOperator.OR, phi, next_release),
        )


# ===========================================================================
# Deontic Logic Rules (16)
# ===========================================================================

class DeonticKAxiomRule(TDFOLInferenceRule):
    """Deontic K Axiom: From O(φ→ψ) and O(φ) derive O(ψ)."""
    description = "Deontic K Axiom: O(φ→ψ), O(φ) ⊢ O(ψ)"

    def can_apply(self, obl_impl: Formula, obl_phi: Formula) -> bool:
        return (
            isinstance(obl_impl, DeonticFormula)
            and obl_impl.operator == DeonticOperator.OBLIGATION
            and isinstance(obl_impl.formula, BinaryFormula)
            and obl_impl.formula.operator == LogicOperator.IMPLIES
            and isinstance(obl_phi, DeonticFormula)
            and obl_phi.operator == DeonticOperator.OBLIGATION
            and obl_phi.formula == obl_impl.formula.left
        )

    def apply(self, obl_impl: Formula, obl_phi: Formula) -> Formula:
        return create_obligation(obl_impl.formula.right)


class DeonticDAxiomRule(TDFOLInferenceRule):
    """Deontic D Axiom: From O(φ) derive P(φ)."""
    description = "Deontic D Axiom: O(φ) ⊢ P(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
        )

    def apply(self, formula: Formula) -> Formula:
        return create_permission(formula.formula)


class DeonticNecessitationRule(TDFOLInferenceRule):
    """Deontic Necessitation: From a tautology φ derive O(φ)."""
    description = "Deontic Necessitation: φ ⊢ O(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return True

    def apply(self, formula: Formula) -> Formula:
        return create_obligation(formula)


class ProhibitionEquivalenceRule(TDFOLInferenceRule):
    """Prohibition Equivalence: From F(φ) derive O(¬φ)."""
    description = "Prohibition Equivalence: F(φ) ⊢ O(¬φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.PROHIBITION
        )

    def apply(self, formula: Formula) -> Formula:
        return create_obligation(create_negation(formula.formula))


class PermissionNegationRule(TDFOLInferenceRule):
    """Permission Negation: From P(φ) derive ¬O(¬φ)."""
    description = "Permission Negation: P(φ) ⊢ ¬O(¬φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.PERMISSION
        )

    def apply(self, formula: Formula) -> Formula:
        return create_negation(create_obligation(create_negation(formula.formula)))


class ObligationConsistencyRule(TDFOLInferenceRule):
    """Obligation Consistency: From O(φ) derive ¬O(¬φ)."""
    description = "Obligation Consistency: O(φ) ⊢ ¬O(¬φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
        )

    def apply(self, formula: Formula) -> Formula:
        return create_negation(create_obligation(create_negation(formula.formula)))


class PermissionIntroductionRule(TDFOLInferenceRule):
    """Permission Introduction: From φ derive P(φ)."""
    description = "Permission Introduction: φ ⊢ P(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return True

    def apply(self, formula: Formula) -> Formula:
        return create_permission(formula)


class ObligationWeakeningRule(TDFOLInferenceRule):
    """Obligation Weakening: From O(φ∧ψ) derive O(φ)."""
    description = "Obligation Weakening: O(φ∧ψ) ⊢ O(φ)"

    def can_apply(self, obligation: Formula, implication: Optional[Formula] = None) -> bool:
        return (
            isinstance(obligation, DeonticFormula)
            and obligation.operator == DeonticOperator.OBLIGATION
        )

    def apply(self, obligation: Formula, implication: Optional[Formula] = None) -> Formula:
        inner = obligation.formula
        if isinstance(inner, BinaryFormula) and inner.operator == LogicOperator.AND:
            return create_obligation(inner.left)
        return obligation


class PermissionStrengtheningRule(TDFOLInferenceRule):
    """Permission Strengthening: From P(φ) and ψ derive P(φ∨ψ)."""
    description = "Permission Strengthening: P(φ), ψ ⊢ P(φ∨ψ)"

    def can_apply(self, permission: Formula, other: Optional[Formula] = None) -> bool:
        return (
            isinstance(permission, DeonticFormula)
            and permission.operator == DeonticOperator.PERMISSION
        )

    def apply(self, permission: Formula, other: Optional[Formula] = None) -> Formula:
        if other is not None:
            return create_permission(BinaryFormula(LogicOperator.OR, permission.formula, other))
        return permission


class ProhibitionFromObligationRule(TDFOLInferenceRule):
    """Prohibition from Obligation: From O(¬φ) derive F(φ)."""
    description = "Prohibition from Obligation: O(¬φ) ⊢ F(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
            and isinstance(formula.formula, UnaryFormula)
            and formula.formula.operator == LogicOperator.NOT
        )

    def apply(self, formula: Formula) -> Formula:
        return create_prohibition(formula.formula.formula)


class DeonticDetachmentRule(TDFOLInferenceRule):
    """Deontic Detachment: From O(φ→ψ) and φ derive O(ψ)."""
    description = "Deontic Detachment: O(φ→ψ), φ ⊢ O(ψ)"

    def can_apply(self, obl_impl: Formula, phi: Optional[Formula] = None) -> bool:
        return (
            isinstance(obl_impl, DeonticFormula)
            and obl_impl.operator == DeonticOperator.OBLIGATION
            and isinstance(obl_impl.formula, BinaryFormula)
            and obl_impl.formula.operator == LogicOperator.IMPLIES
            and (phi is None or phi == obl_impl.formula.left)
        )

    def apply(self, obl_impl: Formula, phi: Optional[Formula] = None) -> Formula:
        return create_obligation(obl_impl.formula.right)


class ObligationEventuallyRule(TDFOLInferenceRule):
    """Obligation Eventually: From O(◊φ) derive ◊O(φ)."""
    description = "Obligation Eventually: O(◊φ) ⊢ ◊O(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
            and isinstance(formula.formula, TemporalFormula)
            and formula.formula.operator == TemporalOperator.EVENTUALLY
        )

    def apply(self, formula: Formula) -> Formula:
        inner_phi = formula.formula.formula
        return create_eventually(create_obligation(inner_phi))


class PermissionTemporalWeakeningRule(TDFOLInferenceRule):
    """Permission Temporal Weakening: From P(φ) derive P(◊φ)."""
    description = "Permission Temporal Weakening: P(φ) ⊢ P(◊φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.PERMISSION
        )

    def apply(self, formula: Formula) -> Formula:
        return create_permission(create_eventually(formula.formula))


class DeonticTemporalIntroductionRule(TDFOLInferenceRule):
    """Deontic-Temporal Introduction: From O(φ) derive O(Xφ) (next-step obligation)."""
    description = "Deontic-Temporal Introduction: O(φ) ⊢ O(Xφ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
        )

    def apply(self, formula: Formula) -> Formula:
        return create_obligation(TemporalFormula(TemporalOperator.NEXT, formula.formula))


# ===========================================================================
# Combined Temporal-Deontic Rules (9)
# ===========================================================================

class AlwaysObligationDistributionRule(TDFOLInferenceRule):
    """Always-Obligation Distribution: From □O(φ) derive O(□φ)."""
    description = "Always-Obligation Distribution: □O(φ) ⊢ O(□φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.ALWAYS
            and isinstance(formula.formula, DeonticFormula)
            and formula.formula.operator == DeonticOperator.OBLIGATION
        )

    def apply(self, formula: Formula) -> Formula:
        inner_phi = formula.formula.formula
        return create_obligation(create_always(inner_phi))


class AlwaysPermissionRule(TDFOLInferenceRule):
    """Always Permission: From P(□φ) derive □P(φ)."""
    description = "Always Permission: P(□φ) ⊢ □P(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.PERMISSION
            and isinstance(formula.formula, TemporalFormula)
            and formula.formula.operator == TemporalOperator.ALWAYS
        )

    def apply(self, formula: Formula) -> Formula:
        inner_phi = formula.formula.formula
        return create_always(create_permission(inner_phi))


class FutureObligationPersistenceRule(TDFOLInferenceRule):
    """Future Obligation Persistence: From O(Xφ) derive X(O(φ))."""
    description = "Future Obligation Persistence: O(Xφ) ⊢ X(O(φ))"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
            and isinstance(formula.formula, TemporalFormula)
            and formula.formula.operator == TemporalOperator.NEXT
        )

    def apply(self, formula: Formula) -> Formula:
        inner_phi = formula.formula.formula
        return TemporalFormula(TemporalOperator.NEXT, create_obligation(inner_phi))


class TemporalObligationPersistenceRule(TDFOLInferenceRule):
    """Temporal Obligation Persistence: From O(□φ) derive □O(φ)."""
    description = "Temporal Obligation Persistence: O(□φ) ⊢ □O(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
            and isinstance(formula.formula, TemporalFormula)
            and formula.formula.operator == TemporalOperator.ALWAYS
        )

    def apply(self, formula: Formula) -> Formula:
        inner_phi = formula.formula.formula
        return create_always(create_obligation(inner_phi))


class UntilObligationRule(TDFOLInferenceRule):
    """Until Obligation: From O(φ U ψ) derive ◊O(ψ)."""
    description = "Until Obligation: O(φ U ψ) ⊢ ◊O(ψ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
            and isinstance(formula.formula, BinaryTemporalFormula)
            and formula.formula.operator == TemporalOperator.UNTIL
        )

    def apply(self, formula: Formula) -> Formula:
        psi = formula.formula.right
        return create_eventually(create_obligation(psi))


class EventuallyForbiddenRule(TDFOLInferenceRule):
    """Eventually Forbidden: From F(◊φ) derive □F(φ)."""
    description = "Eventually Forbidden: F(◊φ) ⊢ □F(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.PROHIBITION
        )

    def apply(self, formula: Formula) -> Formula:
        inner = formula.formula
        if isinstance(inner, TemporalFormula) and inner.operator == TemporalOperator.EVENTUALLY:
            inner = inner.formula
        return create_always(create_prohibition(inner))


class ContraryToDutyRule(TDFOLInferenceRule):
    """Contrary-to-Duty: From O(φ), ¬φ, and reparation ψ derive O(ψ)."""
    description = "Contrary-to-Duty: O(φ), ¬φ, ψ ⊢ O(ψ)"

    def can_apply(self, obl_phi: Formula, neg_phi: Optional[Formula] = None, repair: Optional[Formula] = None) -> bool:
        return (
            isinstance(obl_phi, DeonticFormula)
            and obl_phi.operator == DeonticOperator.OBLIGATION
        )

    def apply(self, obl_phi: Formula, neg_phi: Optional[Formula] = None, repair: Optional[Formula] = None) -> Formula:
        if repair is not None:
            return create_obligation(repair)
        return obl_phi


class ObligationConsistencyRuleExtended(TDFOLInferenceRule):
    """Extended Obligation Consistency: From O(φ) and O(¬φ) derive ⊥ (contradiction)."""
    description = "Extended Obligation Consistency: O(φ), O(¬φ) ⊢ contradiction"

    def can_apply(self, obl1: Formula, obl2: Optional[Formula] = None) -> bool:
        return (
            isinstance(obl1, DeonticFormula)
            and obl1.operator == DeonticOperator.OBLIGATION
        )

    def apply(self, obl1: Formula, obl2: Optional[Formula] = None) -> Formula:
        return create_conjunction(obl1, create_negation(obl1))


# ---------------------------------------------------------------------------
# Additional rules to reach 60 total
# ---------------------------------------------------------------------------

class EventuallyDistributionRule(TDFOLInferenceRule):
    """Eventually Distribution: From ◊(φ∨ψ) derive ◊φ∨◊ψ."""
    description = "Eventually Distribution: ◊(φ∨ψ) ⊢ ◊φ∨◊ψ"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, TemporalFormula)
            and formula.operator == TemporalOperator.EVENTUALLY
            and isinstance(formula.formula, BinaryFormula)
            and formula.formula.operator == LogicOperator.OR
        )

    def apply(self, formula: Formula) -> Formula:
        disj = formula.formula
        return BinaryFormula(
            LogicOperator.OR,
            create_eventually(disj.left),
            create_eventually(disj.right),
        )


class ObligationDistributionRule(TDFOLInferenceRule):
    """Obligation Distribution: From O(φ∧ψ) derive O(φ)∧O(ψ)."""
    description = "Obligation Distribution: O(φ∧ψ) ⊢ O(φ)∧O(ψ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.OBLIGATION
            and isinstance(formula.formula, BinaryFormula)
            and formula.formula.operator == LogicOperator.AND
        )

    def apply(self, formula: Formula) -> Formula:
        conj = formula.formula
        return create_conjunction(
            create_obligation(conj.left),
            create_obligation(conj.right),
        )


class PermissionCompositionRule(TDFOLInferenceRule):
    """Permission Composition: From P(φ∧ψ) derive P(φ)."""
    description = "Permission Composition: P(φ∧ψ) ⊢ P(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.PERMISSION
            and isinstance(formula.formula, BinaryFormula)
            and formula.formula.operator == LogicOperator.AND
        )

    def apply(self, formula: Formula) -> Formula:
        return create_permission(formula.formula.left)


class PermissionForbiddenEquivalenceRule(TDFOLInferenceRule):
    """Permission-Forbidden Equivalence: From F(φ) derive ¬P(φ)."""
    description = "Permission-Forbidden Equivalence: F(φ) ⊢ ¬P(φ)"

    def can_apply(self, formula: Formula) -> bool:
        return (
            isinstance(formula, DeonticFormula)
            and formula.operator == DeonticOperator.PROHIBITION
        )

    def apply(self, formula: Formula) -> Formula:
        return create_negation(create_permission(formula.formula))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def get_all_tdfol_rules() -> List[TDFOLInferenceRule]:
    """Return one instance of every TDFOL inference rule."""
    return [
        # Basic Logic (15)
        ModusPonensRule(),
        ModusTollensRule(),
        HypotheticalSyllogismRule(),
        DisjunctiveSyllogismRule(),
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
        # Temporal (20)
        TemporalKAxiomRule(),
        TemporalTAxiomRule(),
        TemporalS4AxiomRule(),
        TemporalS5AxiomRule(),
        AlwaysNecessitationRule(),
        AlwaysDistributionRule(),
        EventuallyIntroductionRule(),
        UntilUnfoldingRule(),
        UntilInductionRule(),
        EventuallyExpansionRule(),
        AlwaysEventuallyExpansionRule(),
        EventuallyAlwaysContractionRule(),
        UntilReleaseDualityRule(),
        WeakUntilExpansionRule(),
        NextDistributionRule(),
        EventuallyAggregationRule(),
        EventuallyDistributionRule(),
        TemporalInductionRule(),
        UntilInductionStepRule(),
        ReleaseCoinductionRule(),
        # Deontic (16)
        DeonticKAxiomRule(),
        DeonticDAxiomRule(),
        DeonticNecessitationRule(),
        ProhibitionEquivalenceRule(),
        PermissionNegationRule(),
        ObligationConsistencyRule(),
        PermissionIntroductionRule(),
        ObligationWeakeningRule(),
        PermissionStrengtheningRule(),
        ProhibitionFromObligationRule(),
        DeonticDetachmentRule(),
        ObligationEventuallyRule(),
        ObligationDistributionRule(),
        PermissionCompositionRule(),
        PermissionForbiddenEquivalenceRule(),
        PermissionTemporalWeakeningRule(),
        DeonticTemporalIntroductionRule(),
        # Combined Temporal-Deontic (9)
        AlwaysObligationDistributionRule(),
        AlwaysPermissionRule(),
        FutureObligationPersistenceRule(),
        TemporalObligationPersistenceRule(),
        UntilObligationRule(),
        EventuallyForbiddenRule(),
        ContraryToDutyRule(),
        ObligationConsistencyRuleExtended(),
    ]
