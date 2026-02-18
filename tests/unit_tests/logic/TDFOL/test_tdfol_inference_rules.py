"""
Tests for TDFOL Inference Rules Module

This module comprehensively tests the 60 inference rules for TDFOL:
- 15 Basic Logic Rules
- 20 Temporal Logic Rules
- 16 Deontic Logic Rules
- 9 Combined Temporal-Deontic Rules
"""

import pytest

from ipfs_datasets_py.logic.TDFOL import (
    BinaryFormula,
    BinaryTemporalFormula,
    Constant,
    DeonticFormula,
    DeonticOperator,
    LogicOperator,
    Predicate,
    Quantifier,
    QuantifiedFormula,
    TemporalFormula,
    TemporalOperator,
    UnaryFormula,
    Variable,
    create_always,
    create_conjunction,
    create_eventually,
    create_implication,
    create_negation,
    create_obligation,
    create_permission,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_inference_rules import (
    AlwaysDistributionRule,
    AlwaysEventuallyExpansionRule,
    AlwaysNecessitationRule,
    AlwaysObligationDistributionRule,
    AlwaysPermissionRule,
    ConjunctionEliminationLeftRule,
    ConjunctionEliminationRightRule,
    ConjunctionIntroductionRule,
    ContrapositionRule,
    ContraryToDutyRule,
    DeMorganAndRule,
    DeMorganOrRule,
    DeonticDAxiomRule,
    DeonticDetachmentRule,
    DeonticKAxiomRule,
    DeonticNecessitationRule,
    DeonticTemporalIntroductionRule,
    DisjunctionIntroductionLeftRule,
    DisjunctiveSyllogismRule,
    DoubleNegationEliminationRule,
    DoubleNegationIntroductionRule,
    EventuallyAggregationRule,
    EventuallyAlwaysContractionRule,
    EventuallyExpansionRule,
    EventuallyForbiddenRule,
    EventuallyIntroductionRule,
    ExistentialGeneralizationRule,
    FutureObligationPersistenceRule,
    HypotheticalSyllogismRule,
    ModusPonensRule,
    ModusTollensRule,
    NextDistributionRule,
    ObligationConsistencyRule,
    ObligationEventuallyRule,
    ObligationWeakeningRule,
    PermissionIntroductionRule,
    PermissionNegationRule,
    PermissionStrengtheningRule,
    PermissionTemporalWeakeningRule,
    ProhibitionEquivalenceRule,
    ProhibitionFromObligationRule,
    ReleaseCoinductionRule,
    TemporalInductionRule,
    TemporalKAxiomRule,
    TemporalObligationPersistenceRule,
    TemporalS4AxiomRule,
    TemporalS5AxiomRule,
    TemporalTAxiomRule,
    UniversalInstantiationRule,
    UntilInductionRule,
    UntilInductionStepRule,
    UntilObligationRule,
    UntilReleaseDualityRule,
    UntilUnfoldingRule,
    WeakUntilExpansionRule,
    get_all_tdfol_rules,
)


# ============================================================================
# Basic Logic Rules Tests (15 tests)
# ============================================================================


class TestBasicInferenceRules:
    """Test basic first-order logic inference rules."""

    def test_modus_ponens_valid_application(self):
        """
        GIVEN a formula φ and an implication φ → ψ
        WHEN modus ponens is applied
        THEN it should derive ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        impl = create_implication(p, q)
        rule = ModusPonensRule()

        # WHEN
        can_apply = rule.can_apply(p, impl)
        result = rule.apply(p, impl)

        # THEN
        assert can_apply is True
        assert result == q

    def test_modus_ponens_invalid_application(self):
        """
        GIVEN a formula φ and an unrelated implication
        WHEN checking if modus ponens can apply
        THEN it should return False
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        impl = create_implication(q, r)  # q → r, not p → something
        rule = ModusPonensRule()

        # WHEN
        can_apply = rule.can_apply(p, impl)

        # THEN
        assert can_apply is False

    def test_modus_tollens_valid_application(self):
        """
        GIVEN an implication φ → ψ and ¬ψ
        WHEN modus tollens is applied
        THEN it should derive ¬φ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        impl = create_implication(p, q)
        not_q = create_negation(q)
        rule = ModusTollensRule()

        # WHEN
        can_apply = rule.can_apply(impl, not_q)
        result = rule.apply(impl, not_q)

        # THEN
        assert can_apply is True
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT
        assert result.formula == p

    def test_hypothetical_syllogism_valid_application(self):
        """
        GIVEN implications φ → ψ and ψ → χ
        WHEN hypothetical syllogism is applied
        THEN it should derive φ → χ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        r = Predicate("R", ())
        impl1 = create_implication(p, q)
        impl2 = create_implication(q, r)
        rule = HypotheticalSyllogismRule()

        # WHEN
        can_apply = rule.can_apply(impl1, impl2)
        result = rule.apply(impl1, impl2)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.IMPLIES
        assert result.left == p
        assert result.right == r

    def test_disjunctive_syllogism_valid_application(self):
        """
        GIVEN a disjunction φ ∨ ψ and ¬φ
        WHEN disjunctive syllogism is applied
        THEN it should derive ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        disj = BinaryFormula(LogicOperator.OR, p, q)
        not_p = create_negation(p)
        rule = DisjunctiveSyllogismRule()

        # WHEN
        can_apply = rule.can_apply(disj, not_p)
        result = rule.apply(disj, not_p)

        # THEN
        assert can_apply is True
        assert result == q

    def test_conjunction_introduction(self):
        """
        GIVEN two formulas φ and ψ
        WHEN conjunction introduction is applied
        THEN it should derive φ ∧ ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        rule = ConjunctionIntroductionRule()

        # WHEN
        can_apply = rule.can_apply(p, q)
        result = rule.apply(p, q)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
        assert result.left == p
        assert result.right == q

    def test_conjunction_elimination_left(self):
        """
        GIVEN a conjunction φ ∧ ψ
        WHEN conjunction elimination left is applied
        THEN it should derive φ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        rule = ConjunctionEliminationLeftRule()

        # WHEN
        can_apply = rule.can_apply(conj)
        result = rule.apply(conj)

        # THEN
        assert can_apply is True
        assert result == p

    def test_conjunction_elimination_right(self):
        """
        GIVEN a conjunction φ ∧ ψ
        WHEN conjunction elimination right is applied
        THEN it should derive ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        rule = ConjunctionEliminationRightRule()

        # WHEN
        can_apply = rule.can_apply(conj)
        result = rule.apply(conj)

        # THEN
        assert can_apply is True
        assert result == q

    def test_disjunction_introduction_left(self):
        """
        GIVEN a formula φ
        WHEN disjunction introduction left is applied
        THEN it should derive φ ∨ ψ for some ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        rule = DisjunctionIntroductionLeftRule()

        # WHEN
        can_apply = rule.can_apply(p, q)
        result = rule.apply(p, q)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR
        assert result.left == p
        assert result.right == q

    def test_double_negation_elimination(self):
        """
        GIVEN a double negation ¬¬φ
        WHEN double negation elimination is applied
        THEN it should derive φ
        """
        # GIVEN
        p = Predicate("P", ())
        not_p = create_negation(p)
        not_not_p = create_negation(not_p)
        rule = DoubleNegationEliminationRule()

        # WHEN
        can_apply = rule.can_apply(not_not_p)
        result = rule.apply(not_not_p)

        # THEN
        assert can_apply is True
        assert result == p

    def test_double_negation_introduction(self):
        """
        GIVEN a formula φ
        WHEN double negation introduction is applied
        THEN it should derive ¬¬φ
        """
        # GIVEN
        p = Predicate("P", ())
        rule = DoubleNegationIntroductionRule()

        # WHEN
        can_apply = rule.can_apply(p)
        result = rule.apply(p)

        # THEN
        assert can_apply is True
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT
        assert isinstance(result.formula, UnaryFormula)
        assert result.formula.operator == LogicOperator.NOT
        assert result.formula.formula == p

    def test_contraposition(self):
        """
        GIVEN an implication φ → ψ
        WHEN contraposition is applied
        THEN it should derive ¬ψ → ¬φ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        impl = create_implication(p, q)
        rule = ContrapositionRule()

        # WHEN
        can_apply = rule.can_apply(impl)
        result = rule.apply(impl)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.IMPLIES
        assert isinstance(result.left, UnaryFormula)
        assert result.left.formula == q
        assert isinstance(result.right, UnaryFormula)
        assert result.right.formula == p

    def test_de_morgan_and(self):
        """
        GIVEN ¬(φ ∧ ψ)
        WHEN De Morgan's law for AND is applied
        THEN it should derive ¬φ ∨ ¬ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        not_conj = create_negation(conj)
        rule = DeMorganAndRule()

        # WHEN
        can_apply = rule.can_apply(not_conj)
        result = rule.apply(not_conj)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR
        assert isinstance(result.left, UnaryFormula)
        assert isinstance(result.right, UnaryFormula)

    def test_de_morgan_or(self):
        """
        GIVEN ¬(φ ∨ ψ)
        WHEN De Morgan's law for OR is applied
        THEN it should derive ¬φ ∧ ¬ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        disj = BinaryFormula(LogicOperator.OR, p, q)
        not_disj = create_negation(disj)
        rule = DeMorganOrRule()

        # WHEN
        can_apply = rule.can_apply(not_disj)
        result = rule.apply(not_disj)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
        assert isinstance(result.left, UnaryFormula)
        assert isinstance(result.right, UnaryFormula)

    def test_universal_instantiation(self):
        """
        GIVEN ∀x.φ(x)
        WHEN universal instantiation is applied with term t
        THEN it should derive φ(t)
        """
        # GIVEN
        x = Variable("x")
        p = Predicate("P", (x,))
        forall = QuantifiedFormula(Quantifier.FORALL, x, p)
        rule = UniversalInstantiationRule()

        # WHEN
        can_apply = rule.can_apply(forall)
        result = rule.apply(forall)

        # THEN
        assert can_apply is True
        # Result should have variable substituted with constant
        assert isinstance(result, Predicate)

    def test_existential_generalization(self):
        """
        GIVEN φ(t)
        WHEN existential generalization is applied
        THEN it should derive ∃x.φ(x)
        """
        # GIVEN
        t = Constant("john")
        p = Predicate("Person", (t,))
        rule = ExistentialGeneralizationRule()

        # WHEN
        can_apply = rule.can_apply(p)
        result = rule.apply(p)

        # THEN
        assert can_apply is True
        assert isinstance(result, QuantifiedFormula)
        assert result.quantifier == Quantifier.EXISTS


# ============================================================================
# Temporal Logic Rules Tests (10 tests)
# ============================================================================


class TestTemporalInferenceRules:
    """Test temporal logic inference rules (LTL operators)."""

    def test_temporal_k_axiom(self):
        """
        GIVEN □(φ → ψ) and □φ
        WHEN temporal K axiom is applied
        THEN it should derive □ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        impl = create_implication(p, q)
        always_impl = create_always(impl)
        always_p = create_always(p)
        rule = TemporalKAxiomRule()

        # WHEN
        can_apply = rule.can_apply(always_impl, always_p)
        result = rule.apply(always_impl, always_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert result.formula == q

    def test_temporal_t_axiom(self):
        """
        GIVEN □φ
        WHEN temporal T axiom is applied
        THEN it should derive φ
        """
        # GIVEN
        p = Predicate("P", ())
        always_p = create_always(p)
        rule = TemporalTAxiomRule()

        # WHEN
        can_apply = rule.can_apply(always_p)
        result = rule.apply(always_p)

        # THEN
        assert can_apply is True
        assert result == p

    def test_temporal_s4_axiom(self):
        """
        GIVEN □φ
        WHEN temporal S4 axiom is applied
        THEN it should derive □□φ
        """
        # GIVEN
        p = Predicate("P", ())
        always_p = create_always(p)
        rule = TemporalS4AxiomRule()

        # WHEN
        can_apply = rule.can_apply(always_p)
        result = rule.apply(always_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert result.formula == always_p

    def test_temporal_s5_axiom(self):
        """
        GIVEN ◊φ
        WHEN temporal S5 axiom is applied
        THEN it should derive □◊φ
        """
        # GIVEN
        p = Predicate("P", ())
        eventually_p = create_eventually(p)
        rule = TemporalS5AxiomRule()

        # WHEN
        can_apply = rule.can_apply(eventually_p)
        result = rule.apply(eventually_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert result.formula == eventually_p

    def test_eventually_introduction(self):
        """
        GIVEN φ
        WHEN eventually introduction is applied
        THEN it should derive ◊φ
        """
        # GIVEN
        p = Predicate("P", ())
        rule = EventuallyIntroductionRule()

        # WHEN
        can_apply = rule.can_apply(p)
        result = rule.apply(p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.EVENTUALLY
        assert result.formula == p

    def test_always_necessitation(self):
        """
        GIVEN a theorem φ
        WHEN always necessitation is applied
        THEN it should derive □φ
        """
        # GIVEN
        p = Predicate("P", ())
        rule = AlwaysNecessitationRule()

        # WHEN
        can_apply = rule.can_apply(p)
        result = rule.apply(p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert result.formula == p

    def test_until_unfolding(self):
        """
        GIVEN φ U ψ
        WHEN until unfolding is applied
        THEN it should derive ψ ∨ (φ ∧ X(φ U ψ))
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        until = BinaryTemporalFormula(TemporalOperator.UNTIL, p, q)
        rule = UntilUnfoldingRule()

        # WHEN
        can_apply = rule.can_apply(until)
        result = rule.apply(until)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR
        assert result.left == q

    def test_until_induction(self):
        """
        GIVEN ψ ∨ (φ ∧ X(φ U ψ))
        WHEN until induction is applied
        THEN it should derive φ U ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        until = BinaryTemporalFormula(TemporalOperator.UNTIL, p, q)
        next_until = TemporalFormula(TemporalOperator.NEXT, until)
        conj = BinaryFormula(LogicOperator.AND, p, next_until)
        disj = BinaryFormula(LogicOperator.OR, q, conj)
        rule = UntilInductionRule()

        # WHEN
        can_apply = rule.can_apply(disj)
        result = rule.apply(disj)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryTemporalFormula)
        assert result.operator == TemporalOperator.UNTIL

    def test_eventually_expansion(self):
        """
        GIVEN ◊φ
        WHEN eventually expansion is applied
        THEN it should derive φ ∨ X◊φ
        """
        # GIVEN
        p = Predicate("P", ())
        eventually_p = create_eventually(p)
        rule = EventuallyExpansionRule()

        # WHEN
        can_apply = rule.can_apply(eventually_p)
        result = rule.apply(eventually_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR
        assert result.left == p

    def test_always_distribution(self):
        """
        GIVEN □(φ ∧ ψ)
        WHEN always distribution is applied
        THEN it should derive □φ ∧ □ψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        always_conj = create_always(conj)
        rule = AlwaysDistributionRule()

        # WHEN
        can_apply = rule.can_apply(always_conj)
        result = rule.apply(always_conj)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND
        assert isinstance(result.left, TemporalFormula)
        assert isinstance(result.right, TemporalFormula)


# ============================================================================
# Extended Temporal Logic Rules Tests (10 additional tests)
# ============================================================================


class TestExtendedTemporalRules:
    """Test extended temporal logic rules added in Phase 8."""

    def test_always_eventually_expansion(self):
        """
        GIVEN □◊φ
        WHEN always-eventually expansion is applied
        THEN it should derive ◊φ
        """
        # GIVEN
        p = Predicate("P", ())
        eventually_p = create_eventually(p)
        always_eventually_p = create_always(eventually_p)
        rule = AlwaysEventuallyExpansionRule()

        # WHEN
        can_apply = rule.can_apply(always_eventually_p)
        result = rule.apply(always_eventually_p)

        # THEN
        assert can_apply is True
        assert result == eventually_p

    def test_eventually_always_contraction(self):
        """
        GIVEN ◊□φ and φ
        WHEN eventually-always contraction is applied
        THEN it should derive □φ
        """
        # GIVEN
        p = Predicate("P", ())
        always_p = create_always(p)
        eventually_always_p = create_eventually(always_p)
        rule = EventuallyAlwaysContractionRule()

        # WHEN
        can_apply = rule.can_apply(eventually_always_p, p)
        result = rule.apply(eventually_always_p, p)

        # THEN
        assert can_apply is True
        assert result == always_p

    def test_until_release_duality(self):
        """
        GIVEN φ U ψ
        WHEN until-release duality is applied
        THEN it should derive ¬(¬φ R ¬ψ)
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        until = BinaryTemporalFormula(TemporalOperator.UNTIL, p, q)
        rule = UntilReleaseDualityRule()

        # WHEN
        can_apply = rule.can_apply(until)
        result = rule.apply(until)

        # THEN
        assert can_apply is True
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT

    def test_weak_until_expansion(self):
        """
        GIVEN φ W ψ
        WHEN weak until expansion is applied
        THEN it should derive (φ U ψ) ∨ □φ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        weak_until = BinaryTemporalFormula(TemporalOperator.WEAK_UNTIL, p, q)
        rule = WeakUntilExpansionRule()

        # WHEN
        can_apply = rule.can_apply(weak_until)
        result = rule.apply(weak_until)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR

    def test_next_distribution(self):
        """
        GIVEN X(φ ∧ ψ)
        WHEN next distribution is applied
        THEN it should derive Xφ ∧ Xψ
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        next_conj = TemporalFormula(TemporalOperator.NEXT, conj)
        rule = NextDistributionRule()

        # WHEN
        can_apply = rule.can_apply(next_conj)
        result = rule.apply(next_conj)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND

    def test_eventually_aggregation(self):
        """
        GIVEN ◊φ ∨ ◊ψ
        WHEN eventually aggregation is applied
        THEN it should derive ◊(φ ∨ ψ)
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        eventually_p = create_eventually(p)
        eventually_q = create_eventually(q)
        disj = BinaryFormula(LogicOperator.OR, eventually_p, eventually_q)
        rule = EventuallyAggregationRule()

        # WHEN
        can_apply = rule.can_apply(disj)
        result = rule.apply(disj)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.EVENTUALLY

    def test_temporal_induction(self):
        """
        GIVEN □(φ → Xφ) and φ
        WHEN temporal induction is applied
        THEN it should derive □φ
        """
        # GIVEN
        p = Predicate("P", ())
        next_p = TemporalFormula(TemporalOperator.NEXT, p)
        impl = create_implication(p, next_p)
        always_impl = create_always(impl)
        rule = TemporalInductionRule()

        # WHEN
        can_apply = rule.can_apply(always_impl, p)
        result = rule.apply(always_impl, p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert result.formula == p

    def test_until_induction_step(self):
        """
        GIVEN φ U ψ
        WHEN until induction step is applied
        THEN it should derive ψ ∨ (φ ∧ X(φ U ψ))
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        until = BinaryTemporalFormula(TemporalOperator.UNTIL, p, q)
        rule = UntilInductionStepRule()

        # WHEN
        can_apply = rule.can_apply(until)
        result = rule.apply(until)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.OR

    def test_release_coinduction(self):
        """
        GIVEN φ R ψ
        WHEN release coinduction is applied
        THEN it should derive ψ ∧ (φ ∨ X(φ R ψ))
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        release = BinaryTemporalFormula(TemporalOperator.RELEASE, p, q)
        rule = ReleaseCoinductionRule()

        # WHEN
        can_apply = rule.can_apply(release)
        result = rule.apply(release)

        # THEN
        assert can_apply is True
        assert isinstance(result, BinaryFormula)
        assert result.operator == LogicOperator.AND


# ============================================================================
# Deontic Logic Rules Tests (8 tests)
# ============================================================================


class TestDeonticInferenceRules:
    """Test deontic logic inference rules (SDL operators)."""

    def test_deontic_k_axiom(self):
        """
        GIVEN O(φ → ψ) and O(φ)
        WHEN deontic K axiom is applied
        THEN it should derive O(ψ)
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        impl = create_implication(p, q)
        obligation_impl = create_obligation(impl)
        obligation_p = create_obligation(p)
        rule = DeonticKAxiomRule()

        # WHEN
        can_apply = rule.can_apply(obligation_impl, obligation_p)
        result = rule.apply(obligation_impl, obligation_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert result.formula == q

    def test_deontic_d_axiom(self):
        """
        GIVEN O(φ)
        WHEN deontic D axiom is applied
        THEN it should derive P(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        obligation_p = create_obligation(p)
        rule = DeonticDAxiomRule()

        # WHEN
        can_apply = rule.can_apply(obligation_p)
        result = rule.apply(obligation_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PERMISSION
        assert result.formula == p

    def test_prohibition_equivalence(self):
        """
        GIVEN F(φ)
        WHEN prohibition equivalence is applied
        THEN it should derive O(¬φ)
        """
        # GIVEN
        p = Predicate("P", ())
        prohibition_p = DeonticFormula(DeonticOperator.PROHIBITION, p)
        rule = ProhibitionEquivalenceRule()

        # WHEN
        can_apply = rule.can_apply(prohibition_p)
        result = rule.apply(prohibition_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert isinstance(result.formula, UnaryFormula)
        assert result.formula.formula == p

    def test_permission_negation(self):
        """
        GIVEN P(φ)
        WHEN permission negation is applied
        THEN it should derive ¬O(¬φ)
        """
        # GIVEN
        p = Predicate("P", ())
        permission_p = create_permission(p)
        rule = PermissionNegationRule()

        # WHEN
        can_apply = rule.can_apply(permission_p)
        result = rule.apply(permission_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT

    def test_obligation_consistency(self):
        """
        GIVEN O(φ)
        WHEN obligation consistency is applied
        THEN it should derive ¬O(¬φ)
        """
        # GIVEN
        p = Predicate("P", ())
        obligation_p = create_obligation(p)
        rule = ObligationConsistencyRule()

        # WHEN
        can_apply = rule.can_apply(obligation_p)
        result = rule.apply(obligation_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, UnaryFormula)
        assert result.operator == LogicOperator.NOT

    def test_permission_introduction(self):
        """
        GIVEN φ
        WHEN permission introduction is applied
        THEN it should derive P(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        rule = PermissionIntroductionRule()

        # WHEN
        can_apply = rule.can_apply(p)
        result = rule.apply(p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PERMISSION
        assert result.formula == p

    def test_deontic_necessitation(self):
        """
        GIVEN a theorem φ
        WHEN deontic necessitation is applied
        THEN it should derive O(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        rule = DeonticNecessitationRule()

        # WHEN
        can_apply = rule.can_apply(p)
        result = rule.apply(p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert result.formula == p

    def test_prohibition_from_obligation(self):
        """
        GIVEN O(¬φ)
        WHEN prohibition from obligation is applied
        THEN it should derive F(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        not_p = create_negation(p)
        obligation_not_p = create_obligation(not_p)
        rule = ProhibitionFromObligationRule()

        # WHEN
        can_apply = rule.can_apply(obligation_not_p)
        result = rule.apply(obligation_not_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PROHIBITION
        assert result.formula == p


# ============================================================================
# Extended Deontic Logic Rules Tests (8 additional tests)
# ============================================================================


class TestExtendedDeonticRules:
    """Test extended deontic logic rules added in Phase 8."""

    def test_obligation_weakening(self):
        """
        GIVEN O(φ ∧ ψ)
        WHEN obligation weakening is applied
        THEN it should derive O(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        conj = create_conjunction(p, q)
        obligation_conj = create_obligation(conj)
        rule = ObligationWeakeningRule()

        # WHEN
        can_apply = rule.can_apply(obligation_conj)
        result = rule.apply(obligation_conj)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert result.formula == p

    def test_permission_strengthening(self):
        """
        GIVEN P(φ) and ψ
        WHEN permission strengthening is applied
        THEN it should derive P(φ ∨ ψ)
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        permission_p = create_permission(p)
        rule = PermissionStrengtheningRule()

        # WHEN
        can_apply = rule.can_apply(permission_p, q)
        result = rule.apply(permission_p, q)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PERMISSION
        assert isinstance(result.formula, BinaryFormula)
        assert result.formula.operator == LogicOperator.OR

    def test_contrary_to_duty(self):
        """
        GIVEN O(φ), ¬φ, and reparation ψ
        WHEN contrary-to-duty is applied
        THEN it should derive O(ψ)
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Reparation", ())
        obligation_p = create_obligation(p)
        not_p = create_negation(p)
        rule = ContraryToDutyRule()

        # WHEN
        can_apply = rule.can_apply(obligation_p, not_p, q)
        result = rule.apply(obligation_p, not_p, q)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION

    def test_deontic_detachment(self):
        """
        GIVEN O(φ → ψ) and φ
        WHEN deontic detachment is applied
        THEN it should derive O(ψ)
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        impl = create_implication(p, q)
        obligation_impl = create_obligation(impl)
        rule = DeonticDetachmentRule()

        # WHEN
        can_apply = rule.can_apply(obligation_impl, p)
        result = rule.apply(obligation_impl, p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert result.formula == q


# ============================================================================
# Combined Temporal-Deontic Rules Tests (9 tests)
# ============================================================================


class TestCombinedTemporalDeonticRules:
    """Test combined temporal-deontic inference rules."""

    def test_temporal_obligation_persistence(self):
        """
        GIVEN O(□φ)
        WHEN temporal obligation persistence is applied
        THEN it should derive □O(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        always_p = create_always(p)
        obligation_always_p = create_obligation(always_p)
        rule = TemporalObligationPersistenceRule()

        # WHEN
        can_apply = rule.can_apply(obligation_always_p)
        result = rule.apply(obligation_always_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION

    def test_deontic_temporal_introduction(self):
        """
        GIVEN O(φ)
        WHEN deontic temporal introduction is applied
        THEN it should derive O(Xφ)
        """
        # GIVEN
        p = Predicate("P", ())
        obligation_p = create_obligation(p)
        rule = DeonticTemporalIntroductionRule()

        # WHEN
        can_apply = rule.can_apply(obligation_p)
        result = rule.apply(obligation_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.NEXT

    def test_until_obligation(self):
        """
        GIVEN O(φ U ψ)
        WHEN until obligation is applied
        THEN it should derive ◊O(ψ)
        """
        # GIVEN
        p = Predicate("P", ())
        q = Predicate("Q", ())
        until = BinaryTemporalFormula(TemporalOperator.UNTIL, p, q)
        obligation_until = create_obligation(until)
        rule = UntilObligationRule()

        # WHEN
        can_apply = rule.can_apply(obligation_until)
        result = rule.apply(obligation_until)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.EVENTUALLY

    def test_always_permission(self):
        """
        GIVEN P(□φ)
        WHEN always permission is applied
        THEN it should derive □P(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        always_p = create_always(p)
        permission_always_p = create_permission(always_p)
        rule = AlwaysPermissionRule()

        # WHEN
        can_apply = rule.can_apply(permission_always_p)
        result = rule.apply(permission_always_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PERMISSION

    def test_eventually_forbidden(self):
        """
        GIVEN F(◊φ)
        WHEN eventually forbidden is applied
        THEN it should derive □F(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        eventually_p = create_eventually(p)
        forbidden_eventually_p = DeonticFormula(
            DeonticOperator.PROHIBITION, eventually_p
        )
        rule = EventuallyForbiddenRule()

        # WHEN
        can_apply = rule.can_apply(forbidden_eventually_p)
        result = rule.apply(forbidden_eventually_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.ALWAYS
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.PROHIBITION

    def test_obligation_eventually(self):
        """
        GIVEN O(◊φ)
        WHEN obligation eventually is applied
        THEN it should derive ◊O(φ)
        """
        # GIVEN
        p = Predicate("P", ())
        eventually_p = create_eventually(p)
        obligation_eventually_p = create_obligation(eventually_p)
        rule = ObligationEventuallyRule()

        # WHEN
        can_apply = rule.can_apply(obligation_eventually_p)
        result = rule.apply(obligation_eventually_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.EVENTUALLY
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION

    def test_permission_temporal_weakening(self):
        """
        GIVEN P(φ)
        WHEN permission temporal weakening is applied
        THEN it should derive P(◊φ)
        """
        # GIVEN
        p = Predicate("P", ())
        permission_p = create_permission(p)
        rule = PermissionTemporalWeakeningRule()

        # WHEN
        can_apply = rule.can_apply(permission_p)
        result = rule.apply(permission_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.PERMISSION
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.EVENTUALLY

    def test_always_obligation_distribution(self):
        """
        GIVEN □O(φ)
        WHEN always-obligation distribution is applied
        THEN it should derive O(□φ)
        """
        # GIVEN
        p = Predicate("P", ())
        obligation_p = create_obligation(p)
        always_obligation_p = create_always(obligation_p)
        rule = AlwaysObligationDistributionRule()

        # WHEN
        can_apply = rule.can_apply(always_obligation_p)
        result = rule.apply(always_obligation_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, DeonticFormula)
        assert result.operator == DeonticOperator.OBLIGATION
        assert isinstance(result.formula, TemporalFormula)
        assert result.formula.operator == TemporalOperator.ALWAYS

    def test_future_obligation_persistence(self):
        """
        GIVEN O(Xφ)
        WHEN future obligation persistence is applied
        THEN it should derive X(O(φ))
        """
        # GIVEN
        p = Predicate("P", ())
        next_p = TemporalFormula(TemporalOperator.NEXT, p)
        obligation_next_p = create_obligation(next_p)
        rule = FutureObligationPersistenceRule()

        # WHEN
        can_apply = rule.can_apply(obligation_next_p)
        result = rule.apply(obligation_next_p)

        # THEN
        assert can_apply is True
        assert isinstance(result, TemporalFormula)
        assert result.operator == TemporalOperator.NEXT
        assert isinstance(result.formula, DeonticFormula)
        assert result.formula.operator == DeonticOperator.OBLIGATION


# ============================================================================
# Integration and Registry Tests
# ============================================================================


class TestRuleRegistry:
    """Test the inference rule registry and integration."""

    def test_get_all_tdfol_rules_count(self):
        """
        GIVEN the get_all_tdfol_rules function
        WHEN retrieving all rules
        THEN it should return 60 rules
        """
        # WHEN
        all_rules = get_all_tdfol_rules()

        # THEN
        assert len(all_rules) == 60

    def test_get_all_tdfol_rules_categories(self):
        """
        GIVEN the get_all_tdfol_rules function
        WHEN retrieving all rules
        THEN it should include rules from all categories
        """
        # WHEN
        all_rules = get_all_tdfol_rules()
        rule_names = [rule.name for rule in all_rules]

        # THEN - Check for presence of rules from each category
        # Basic logic
        assert "ModusPonens" in rule_names
        assert "ConjunctionIntroduction" in rule_names

        # Temporal logic
        assert "TemporalKAxiom" in rule_names
        assert "EventuallyIntroduction" in rule_names

        # Deontic logic
        assert "DeonticKAxiom" in rule_names
        assert "PermissionIntroduction" in rule_names

        # Combined temporal-deontic
        assert "TemporalObligationPersistence" in rule_names
        assert "AlwaysObligationDistribution" in rule_names

    def test_rule_descriptions(self):
        """
        GIVEN any inference rule
        WHEN accessing its description
        THEN it should have a non-empty description
        """
        # GIVEN
        all_rules = get_all_tdfol_rules()

        # THEN
        for rule in all_rules:
            assert rule.name
            assert rule.description
            assert len(rule.description) > 0

    def test_rule_repr(self):
        """
        GIVEN any inference rule
        WHEN converting to string
        THEN it should return a readable representation
        """
        # GIVEN
        rule = ModusPonensRule()

        # WHEN
        repr_str = repr(rule)

        # THEN
        assert "ModusPonens" in repr_str
        assert rule.description in repr_str
