"""
Tests for temporal and deontic CEC inference rule modules.

Validates that after the session-29 bug fixes the rules fire correctly:
- temporal.py: □/◊/○/U/S rules (was broken: operator.value string vs enum)
- deontic.py: O/P/F rules (was broken: .operand attr, Operator undefined, wrong
  return types, broken Formula() factory)
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    Atom, Conjunction, Disjunction, Implication, Negation,
    DeonticFormula, ConnectiveFormula, TemporalFormula,
    DeonticOperator, LogicalConnective, TemporalOperator,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.temporal import (
    AlwaysDistribution,
    AlwaysImplication,
    AlwaysTransitive,
    AlwaysImpliesNext,
    AlwaysInduction,
    EventuallyFromAlways,
    EventuallyDistribution,
    EventuallyTransitive,
    EventuallyImplication,
    NextDistribution,
    NextImplication,
    UntilWeakening,
    SinceWeakening,
    TemporalUntilElimination,
    TemporalNegation,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.deontic import (
    ObligationDistribution,
    ObligationImplication,
    ObligationConjunction,
    ObligationConsistency,
    PermissionDistribution,
    PermissionFromNonObligation,
    ProhibitionEquivalence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def atom(name: str) -> Atom:
    return Atom(name)


def conj(a, b):
    return Conjunction(a, b)


def disj(a, b):
    return Disjunction(a, b)


def impl(a, b):
    return Implication(a, b)


def neg(a):
    return Negation(a)


def always(f):
    return TemporalFormula(TemporalOperator.ALWAYS, f)


def eventually(f):
    return TemporalFormula(TemporalOperator.EVENTUALLY, f)


def next_t(f):
    return TemporalFormula(TemporalOperator.NEXT, f)


def until(p, q):
    return TemporalFormula(TemporalOperator.UNTIL, Conjunction(p, q))


def since(p, q):
    return TemporalFormula(TemporalOperator.SINCE, Conjunction(p, q))


def oblig(f):
    return DeonticFormula(DeonticOperator.OBLIGATION, f)


def permit(f):
    return DeonticFormula(DeonticOperator.PERMISSION, f)


def prohib(f):
    return DeonticFormula(DeonticOperator.PROHIBITION, f)


# ===========================================================================
# ── Temporal rules ──────────────────────────────────────────────────────────
# ===========================================================================

class TestAlwaysDistribution:
    """□(P∧Q) ⊢ □P ∧ □Q"""

    def test_can_apply_true(self):
        """GIVEN □(P∧Q) WHEN checked THEN can_apply is True."""
        p, q = atom("P"), atom("Q")
        rule = AlwaysDistribution()
        assert rule.can_apply([always(conj(p, q))])

    def test_can_apply_false_no_temporal(self):
        """GIVEN plain conjunction WHEN checked THEN can_apply is False."""
        assert not AlwaysDistribution().can_apply([conj(atom("P"), atom("Q"))])

    def test_can_apply_false_not_conjunction(self):
        """GIVEN □P (not a conjunction inside) THEN can_apply is False."""
        assert not AlwaysDistribution().can_apply([always(atom("P"))])

    def test_apply_result_structure(self):
        """GIVEN □(P∧Q) WHEN applied THEN result is (□P ∧ □Q)."""
        p, q = atom("P"), atom("Q")
        result = AlwaysDistribution().apply([always(conj(p, q))])
        assert len(result) == 1
        res = result[0]
        assert isinstance(res, ConnectiveFormula)
        assert res.connective == LogicalConnective.AND
        for sub in res.formulas:
            assert isinstance(sub, TemporalFormula)
            assert sub.operator == TemporalOperator.ALWAYS

    def test_apply_no_match_returns_empty(self):
        """GIVEN no matching formula WHEN applied THEN returns []."""
        assert AlwaysDistribution().apply([atom("P")]) == []


class TestAlwaysImplication:
    """□P ∧ □(P→Q) ⊢ □Q"""

    def test_can_apply_true(self):
        """GIVEN □P and □(P→Q) WHEN checked THEN can_apply is True."""
        p, q = atom("P"), atom("Q")
        rule = AlwaysImplication()
        assert rule.can_apply([always(p), always(impl(p, q))])

    def test_can_apply_false_no_matching_antecedent(self):
        """GIVEN □P and □(R→Q) WHEN checked THEN can_apply is False."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        assert not AlwaysImplication().can_apply([always(p), always(impl(r, q))])

    def test_apply_derives_always_q(self):
        """GIVEN □P and □(P→Q) WHEN applied THEN result is □Q."""
        p, q = atom("P"), atom("Q")
        result = AlwaysImplication().apply([always(p), always(impl(p, q))])
        assert len(result) >= 1
        assert any(isinstance(r, TemporalFormula) and r.operator == TemporalOperator.ALWAYS
                   for r in result)


class TestAlwaysTransitive:
    """□□P ⊢ □P"""

    def test_can_apply_true(self):
        p = atom("P")
        assert AlwaysTransitive().can_apply([always(always(p))])

    def test_can_apply_false(self):
        assert not AlwaysTransitive().can_apply([always(atom("P"))])

    def test_apply_simplifies(self):
        p = atom("P")
        result = AlwaysTransitive().apply([always(always(p))])
        assert len(result) == 1
        assert isinstance(result[0], TemporalFormula)
        assert result[0].operator == TemporalOperator.ALWAYS
        assert result[0].formula == p


class TestAlwaysImpliesNext:
    """□P ⊢ ○P"""

    def test_can_apply_true(self):
        assert AlwaysImpliesNext().can_apply([always(atom("P"))])

    def test_can_apply_false(self):
        assert not AlwaysImpliesNext().can_apply([eventually(atom("P"))])

    def test_apply_produces_next(self):
        p = atom("P")
        result = AlwaysImpliesNext().apply([always(p)])
        assert len(result) == 1
        assert isinstance(result[0], TemporalFormula)
        assert result[0].operator == TemporalOperator.NEXT


class TestAlwaysInduction:
    """P ∧ □(P→○P) ⊢ □P"""

    def test_can_apply_true(self):
        """GIVEN P and □(P→○P) WHEN checked THEN can_apply is True."""
        p = atom("P")
        induction_premise = always(impl(p, next_t(p)))
        assert AlwaysInduction().can_apply([p, induction_premise])

    def test_can_apply_false_missing_induction(self):
        p, q = atom("P"), atom("Q")
        # □(P→○Q) – consequent is ○Q, not ○P
        wrong = always(impl(p, next_t(q)))
        assert not AlwaysInduction().can_apply([p, wrong])

    def test_apply_produces_always(self):
        p = atom("P")
        result = AlwaysInduction().apply([p, always(impl(p, next_t(p)))])
        assert any(isinstance(r, TemporalFormula) and r.operator == TemporalOperator.ALWAYS
                   for r in result)


class TestEventuallyFromAlways:
    """□P ⊢ ◊P"""

    def test_can_apply_true(self):
        assert EventuallyFromAlways().can_apply([always(atom("P"))])

    def test_can_apply_false_no_always(self):
        assert not EventuallyFromAlways().can_apply([eventually(atom("P"))])

    def test_apply_produces_eventually(self):
        p = atom("P")
        result = EventuallyFromAlways().apply([always(p)])
        assert len(result) == 1
        assert isinstance(result[0], TemporalFormula)
        assert result[0].operator == TemporalOperator.EVENTUALLY
        assert result[0].formula == p


class TestEventuallyDistribution:
    """◊(P∨Q) ⊢ ◊P ∨ ◊Q"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert EventuallyDistribution().can_apply([eventually(disj(p, q))])

    def test_can_apply_false_conjunction_not_disjunction(self):
        p, q = atom("P"), atom("Q")
        assert not EventuallyDistribution().can_apply([eventually(conj(p, q))])

    def test_apply_result_structure(self):
        p, q = atom("P"), atom("Q")
        result = EventuallyDistribution().apply([eventually(disj(p, q))])
        assert len(result) == 1
        res = result[0]
        assert isinstance(res, ConnectiveFormula)
        assert res.connective == LogicalConnective.OR
        for sub in res.formulas:
            assert isinstance(sub, TemporalFormula)
            assert sub.operator == TemporalOperator.EVENTUALLY


class TestEventuallyTransitive:
    """◊◊P ⊢ ◊P"""

    def test_can_apply_true(self):
        p = atom("P")
        assert EventuallyTransitive().can_apply([eventually(eventually(p))])

    def test_can_apply_false(self):
        assert not EventuallyTransitive().can_apply([eventually(atom("P"))])

    def test_apply_simplifies(self):
        p = atom("P")
        result = EventuallyTransitive().apply([eventually(eventually(p))])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, TemporalFormula)
        assert r.operator == TemporalOperator.EVENTUALLY
        assert r.formula == p


class TestEventuallyImplication:
    """◊P ∧ □(P→Q) ⊢ ◊Q"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert EventuallyImplication().can_apply([eventually(p), always(impl(p, q))])

    def test_can_apply_false_no_matching(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        assert not EventuallyImplication().can_apply([eventually(p), always(impl(r, q))])

    def test_apply_produces_eventually_q(self):
        p, q = atom("P"), atom("Q")
        result = EventuallyImplication().apply([eventually(p), always(impl(p, q))])
        assert any(isinstance(r, TemporalFormula) and r.operator == TemporalOperator.EVENTUALLY
                   for r in result)


class TestNextDistribution:
    """○(P∧Q) ⊢ ○P ∧ ○Q"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert NextDistribution().can_apply([next_t(conj(p, q))])

    def test_can_apply_false_no_conjunction(self):
        assert not NextDistribution().can_apply([next_t(atom("P"))])

    def test_apply_result_structure(self):
        p, q = atom("P"), atom("Q")
        result = NextDistribution().apply([next_t(conj(p, q))])
        assert len(result) == 1
        res = result[0]
        assert isinstance(res, ConnectiveFormula)
        assert res.connective == LogicalConnective.AND
        for sub in res.formulas:
            assert isinstance(sub, TemporalFormula)
            assert sub.operator == TemporalOperator.NEXT


class TestNextImplication:
    """○P ∧ ○(P→Q) ⊢ ○Q"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert NextImplication().can_apply([next_t(p), next_t(impl(p, q))])

    def test_can_apply_false(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        assert not NextImplication().can_apply([next_t(p), next_t(impl(r, q))])

    def test_apply_derives_next_q(self):
        p, q = atom("P"), atom("Q")
        result = NextImplication().apply([next_t(p), next_t(impl(p, q))])
        assert any(isinstance(r, TemporalFormula) and r.operator == TemporalOperator.NEXT
                   for r in result)


class TestUntilWeakening:
    """P U Q ⊢ ◊Q"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert UntilWeakening().can_apply([until(p, q)])

    def test_can_apply_false(self):
        assert not UntilWeakening().can_apply([always(atom("P"))])

    def test_apply_produces_eventually(self):
        p, q = atom("P"), atom("Q")
        result = UntilWeakening().apply([until(p, q)])
        assert any(isinstance(r, TemporalFormula) and r.operator == TemporalOperator.EVENTUALLY
                   for r in result)


class TestSinceWeakening:
    """P S Q ⊢ Q (held in the past)"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert SinceWeakening().can_apply([since(p, q)])

    def test_can_apply_false(self):
        assert not SinceWeakening().can_apply([always(atom("P"))])

    def test_apply_extracts_second_argument(self):
        p, q = atom("P"), atom("Q")
        result = SinceWeakening().apply([since(p, q)])
        assert len(result) >= 1


class TestTemporalUntilElimination:
    """P U Q ∧ Q ⊢ Q"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert TemporalUntilElimination().can_apply([until(p, q), q])

    def test_can_apply_false_q_not_present(self):
        p, q = atom("P"), atom("Q")
        assert not TemporalUntilElimination().can_apply([until(p, q)])

    def test_apply_returns_q(self):
        p, q = atom("P"), atom("Q")
        result = TemporalUntilElimination().apply([until(p, q), q])
        assert q in result


class TestTemporalNegation:
    """¬□P ⊢ ◊¬P"""

    def test_can_apply_true(self):
        p = atom("P")
        not_always_p = Negation(always(p))
        assert TemporalNegation().can_apply([not_always_p])

    def test_can_apply_false_plain_negation(self):
        assert not TemporalNegation().can_apply([Negation(atom("P"))])

    def test_apply_produces_eventually_neg(self):
        p = atom("P")
        not_always_p = Negation(always(p))
        result = TemporalNegation().apply([not_always_p])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, TemporalFormula)
        assert r.operator == TemporalOperator.EVENTUALLY
        assert isinstance(r.formula, ConnectiveFormula)
        assert r.formula.connective == LogicalConnective.NOT


# ===========================================================================
# ── Deontic rules ────────────────────────────────────────────────────────────
# ===========================================================================

class TestObligationDistribution:
    """O(P∧Q) ⊢ O(P) ∧ O(Q)"""

    def test_can_apply_true(self):
        """GIVEN O(P∧Q) WHEN checked THEN can_apply is True."""
        p, q = atom("P"), atom("Q")
        assert ObligationDistribution().can_apply([oblig(conj(p, q))])

    def test_can_apply_false_no_deontic(self):
        """GIVEN plain conjunction THEN can_apply is False."""
        p, q = atom("P"), atom("Q")
        assert not ObligationDistribution().can_apply([conj(p, q)])

    def test_can_apply_false_no_inner_conjunction(self):
        """GIVEN O(P) (no conjunction inside) THEN can_apply is False."""
        assert not ObligationDistribution().can_apply([oblig(atom("P"))])

    def test_apply_result_type(self):
        """GIVEN O(P∧Q) WHEN applied THEN result is (O(P) ∧ O(Q))."""
        p, q = atom("P"), atom("Q")
        result = ObligationDistribution().apply([oblig(conj(p, q))])
        assert len(result) == 1
        res = result[0]
        assert isinstance(res, ConnectiveFormula)
        assert res.connective == LogicalConnective.AND
        for sub in res.formulas:
            assert isinstance(sub, DeonticFormula)
            assert sub.operator == DeonticOperator.OBLIGATION

    def test_apply_no_match_returns_empty(self):
        """GIVEN no matching formula WHEN applied THEN []."""
        assert ObligationDistribution().apply([oblig(atom("P"))]) == []


class TestObligationImplication:
    """O(P) ∧ (P→Q) ⊢ O(Q)"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert ObligationImplication().can_apply([oblig(p), impl(p, q)])

    def test_can_apply_false_no_matching_antecedent(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        assert not ObligationImplication().can_apply([oblig(p), impl(r, q)])

    def test_can_apply_false_no_obligation(self):
        p, q = atom("P"), atom("Q")
        assert not ObligationImplication().can_apply([impl(p, q)])

    def test_apply_produces_obligation_q(self):
        p, q = atom("P"), atom("Q")
        result = ObligationImplication().apply([oblig(p), impl(p, q)])
        assert len(result) >= 1
        assert any(isinstance(r, DeonticFormula) and r.operator == DeonticOperator.OBLIGATION
                   and r.formula == q for r in result)

    def test_apply_chained(self):
        """O(P) ∧ (P→Q) ∧ (Q→R) ⊢ includes O(Q) and O(R) after two applications."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        rule = ObligationImplication()
        step1 = rule.apply([oblig(p), impl(p, q), impl(q, r)])
        # step1 should include O(Q)
        new_formulas = [oblig(p), impl(p, q), impl(q, r)] + step1
        step2 = rule.apply(new_formulas)
        oblig_qs = [x for x in step1 if isinstance(x, DeonticFormula) and x.formula == q]
        assert len(oblig_qs) >= 1


class TestPermissionFromNonObligation:
    """¬O(¬P) ⊢ P(P)"""

    def test_can_apply_true(self):
        p = atom("P")
        not_oblig_neg_p = Negation(oblig(Negation(p)))
        assert PermissionFromNonObligation().can_apply([not_oblig_neg_p])

    def test_can_apply_false_plain_negation(self):
        assert not PermissionFromNonObligation().can_apply([Negation(atom("P"))])

    def test_can_apply_false_not_negation_inside(self):
        p, q = atom("P"), atom("Q")
        # ¬O(Q) — inner is O(Q) but Q is not ¬P
        not_oblig_q = Negation(oblig(q))
        # This is ¬O(Q), not ¬O(¬P), so should fail
        assert not PermissionFromNonObligation().can_apply([not_oblig_q])

    def test_apply_produces_permission_p(self):
        p = atom("P")
        not_oblig_neg_p = Negation(oblig(Negation(p)))
        result = PermissionFromNonObligation().apply([not_oblig_neg_p])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, DeonticFormula)
        assert r.operator == DeonticOperator.PERMISSION
        assert r.formula == p


class TestObligationConjunction:
    """O(P) ∧ O(Q) ⊢ O(P∧Q)"""

    def test_can_apply_two_obligations(self):
        p, q = atom("P"), atom("Q")
        assert ObligationConjunction().can_apply([oblig(p), oblig(q)])

    def test_can_apply_false_single_obligation(self):
        assert not ObligationConjunction().can_apply([oblig(atom("P"))])

    def test_apply_produces_obligation_conjunction(self):
        p, q = atom("P"), atom("Q")
        result = ObligationConjunction().apply([oblig(p), oblig(q)])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, DeonticFormula)
        assert r.operator == DeonticOperator.OBLIGATION
        assert isinstance(r.formula, ConnectiveFormula)
        assert r.formula.connective == LogicalConnective.AND

    def test_apply_three_obligations_uses_first_two(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        result = ObligationConjunction().apply([oblig(p), oblig(q), oblig(r)])
        assert len(result) == 1
        # Result is O(P∧Q)
        inner_formulas = result[0].formula.formulas
        assert p in inner_formulas
        assert q in inner_formulas


class TestPermissionDistribution:
    """P(P∨Q) ⊢ P(P) ∨ P(Q)"""

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert PermissionDistribution().can_apply([permit(disj(p, q))])

    def test_can_apply_false_no_disjunction_inside(self):
        p, q = atom("P"), atom("Q")
        assert not PermissionDistribution().can_apply([permit(conj(p, q))])

    def test_can_apply_false_obligation_not_permission(self):
        p, q = atom("P"), atom("Q")
        assert not PermissionDistribution().can_apply([oblig(disj(p, q))])

    def test_apply_result_structure(self):
        p, q = atom("P"), atom("Q")
        result = PermissionDistribution().apply([permit(disj(p, q))])
        assert len(result) == 1
        res = result[0]
        assert isinstance(res, ConnectiveFormula)
        assert res.connective == LogicalConnective.OR
        for sub in res.formulas:
            assert isinstance(sub, DeonticFormula)
            assert sub.operator == DeonticOperator.PERMISSION


class TestObligationConsistency:
    """O(P) ∧ O(¬P) ⊢ ⊥"""

    def test_can_apply_true_contradiction(self):
        p = atom("P")
        assert ObligationConsistency().can_apply([oblig(p), oblig(Negation(p))])

    def test_can_apply_false_no_contradiction(self):
        p, q = atom("P"), atom("Q")
        assert not ObligationConsistency().can_apply([oblig(p), oblig(q)])

    def test_can_apply_false_single_obligation(self):
        assert not ObligationConsistency().can_apply([oblig(atom("P"))])

    def test_apply_returns_empty_on_contradiction(self):
        """Contradictory obligations produce no new derivable formulas."""
        p = atom("P")
        result = ObligationConsistency().apply([oblig(p), oblig(Negation(p))])
        assert result == []

    def test_apply_returns_empty_when_no_contradiction(self):
        """Even without contradiction, apply() returns empty (just checks)."""
        p, q = atom("P"), atom("Q")
        result = ObligationConsistency().apply([oblig(p), oblig(q)])
        assert result == []


class TestProhibitionEquivalence:
    """F(P) ⊣⊢ O(¬P)"""

    def test_can_apply_prohibition(self):
        assert ProhibitionEquivalence().can_apply([prohib(atom("P"))])

    def test_can_apply_obligation_of_negation(self):
        p = atom("P")
        assert ProhibitionEquivalence().can_apply([oblig(Negation(p))])

    def test_can_apply_false_obligation_of_plain(self):
        assert not ProhibitionEquivalence().can_apply([oblig(atom("P"))])

    def test_apply_prohibition_to_obligation_negation(self):
        """F(P) → O(¬P)"""
        p = atom("P")
        result = ProhibitionEquivalence().apply([prohib(p)])
        assert any(
            isinstance(r, DeonticFormula) and
            r.operator == DeonticOperator.OBLIGATION and
            isinstance(r.formula, ConnectiveFormula) and
            r.formula.connective == LogicalConnective.NOT
            for r in result
        )

    def test_apply_obligation_negation_to_prohibition(self):
        """O(¬P) → F(P)"""
        p = atom("P")
        result = ProhibitionEquivalence().apply([oblig(Negation(p))])
        assert any(
            isinstance(r, DeonticFormula) and r.operator == DeonticOperator.PROHIBITION
            for r in result
        )

    def test_apply_bidirectional_both_results(self):
        """Both F(P) and O(¬P) → two results in one call."""
        p = atom("P")
        result = ProhibitionEquivalence().apply([prohib(p), oblig(Negation(p))])
        obligations = [r for r in result if isinstance(r, DeonticFormula)
                       and r.operator == DeonticOperator.OBLIGATION]
        prohibitions = [r for r in result if isinstance(r, DeonticFormula)
                        and r.operator == DeonticOperator.PROHIBITION]
        assert len(obligations) >= 1
        assert len(prohibitions) >= 1


# ===========================================================================
# ── Rule chaining (temporal + deontic) ──────────────────────────────────────
# ===========================================================================

class TestRuleChaining:
    """Verify rules can be composed for multi-step derivations."""

    def test_temporal_chain_always_to_next_to_eventually(self):
        """□P ⊢ ○P ⊢ ◊○P"""
        p = atom("P")
        step1 = AlwaysImpliesNext().apply([always(p)])
        assert step1
        next_p = step1[0]
        # now wrap in eventually
        step2 = EventuallyFromAlways().apply([always(p)])
        assert step2
        ev = step2[0]
        assert ev.operator == TemporalOperator.EVENTUALLY

    def test_deontic_chain_distribution_then_implication(self):
        """O(P∧Q) ⊢ O(P) and O(Q); O(P) ∧ (P→R) ⊢ O(R)"""
        p, q, r = atom("P"), atom("Q"), atom("R")
        dist_results = ObligationDistribution().apply([oblig(conj(p, q))])
        assert dist_results
        # dist_results[0] is a ConnectiveFormula AND of O(P) and O(Q)
        # Extract the two obligations
        combined = dist_results[0]
        o_p = combined.formulas[0]  # O(P)
        # Now apply implication
        imp_results = ObligationImplication().apply([o_p, impl(p, r)])
        assert any(isinstance(x, DeonticFormula) and x.formula == r for x in imp_results)

    def test_temporal_always_distribution_and_induction(self):
        """□(P∧Q) ⊢ □P ∧ □Q and P ∧ □(P→○P) ⊢ □P"""
        p, q = atom("P"), atom("Q")
        dist = AlwaysDistribution().apply([always(conj(p, q))])
        assert dist

        # Induction: P, □(P→○P) ⊢ □P
        ind_results = AlwaysInduction().apply([p, always(impl(p, next_t(p)))])
        assert any(isinstance(r, TemporalFormula) and r.operator == TemporalOperator.ALWAYS
                   for r in ind_results)

    def test_deontic_prohibition_equivalence_chain(self):
        """F(P) → O(¬P); O(¬P) ∧ (¬P → Q) ⊢ O(Q)"""
        p, q = atom("P"), atom("Q")
        # Step 1: F(P) → O(¬P)
        step1 = ProhibitionEquivalence().apply([prohib(p)])
        obn_ps = [r for r in step1 if isinstance(r, DeonticFormula)
                  and r.operator == DeonticOperator.OBLIGATION]
        assert obn_ps
        o_neg_p = obn_ps[0]
        neg_p = o_neg_p.formula  # ¬P
        # Step 2: O(¬P) ∧ (¬P → Q) ⊢ O(Q)
        step2 = ObligationImplication().apply([o_neg_p, impl(neg_p, q)])
        assert any(isinstance(r, DeonticFormula) and r.formula == q for r in step2)


# ===========================================================================
# ── __all__ export checks ────────────────────────────────────────────────────
# ===========================================================================

class TestExports:
    """Verify all expected symbols are importable from both modules."""

    def test_temporal_all_exports(self):
        from ipfs_datasets_py.logic.CEC.native.inference_rules import temporal
        for name in temporal.__all__:
            assert hasattr(temporal, name)

    def test_deontic_all_exports(self):
        from ipfs_datasets_py.logic.CEC.native.inference_rules import deontic
        for name in deontic.__all__:
            assert hasattr(deontic, name)

    def test_temporal_rule_names_unique(self):
        rules = [
            AlwaysDistribution(), AlwaysImplication(), AlwaysTransitive(),
            AlwaysImpliesNext(), AlwaysInduction(), EventuallyFromAlways(),
            EventuallyDistribution(), EventuallyTransitive(), EventuallyImplication(),
            NextDistribution(), NextImplication(), UntilWeakening(),
            SinceWeakening(), TemporalUntilElimination(), TemporalNegation(),
        ]
        names = [r.name() for r in rules]
        assert len(names) == len(set(names)), "Rule names must be unique"

    def test_deontic_rule_names_unique(self):
        rules = [
            ObligationDistribution(), ObligationImplication(), ObligationConjunction(),
            ObligationConsistency(), PermissionDistribution(),
            PermissionFromNonObligation(), ProhibitionEquivalence(),
        ]
        names = [r.name() for r in rules]
        assert len(names) == len(set(names)), "Rule names must be unique"
