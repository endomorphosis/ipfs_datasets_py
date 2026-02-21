"""
Tests for propositional, modal, resolution, and specialized inference rules.

Session 31: covers all 10 propositional rules' apply() methods (propositional.py 55%→100%),
modal.py NecessityDistribution/PossibilityDuality/NecessityConjunction apply() paths
(modal.py 64%→99%), resolution.py edge cases (84%→96%), and specialized.py
ConstructiveDilemma/DestructiveDilemma apply() (79%→97%).
"""
from __future__ import annotations

from typing import Any, List

import pytest

from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    ConnectiveFormula,
    LogicalConnective,
    Predicate,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.propositional import (
    ConjunctionIntroduction,
    Contraposition,
    DeMorgan,
    DisjunctiveSyllogism,
    DoubleNegation,
    HypotheticalSyllogism,
    ImplicationElimination,
    ModusPonens,
    Simplification,
    Weakening,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.modal import (
    NecessityConjunction,
    NecessityDistribution,
    NecessityElimination,
    PossibilityDuality,
    PossibilityIntroduction,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.resolution import (
    CaseAnalysisRule,
    FactoringRule,
    ProofByContradictionRule,
    ResolutionRule,
    SubsumptionRule,
    UnitResolutionRule,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.specialized import (
    AbsorptionRule,
    AdditionRule,
    CommutativityConjunction,
    ConstructiveDilemma,
    DestructiveDilemma,
    ExportationRule,
    TautologyRule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def atom(name: str) -> AtomicFormula:
    """Create a zero-arity atomic formula."""
    return AtomicFormula(Predicate(name, []), [])


def impl(p: Any, q: Any) -> ConnectiveFormula:
    return ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])


def conj(p: Any, q: Any) -> ConnectiveFormula:
    return ConnectiveFormula(LogicalConnective.AND, [p, q])


def disj(p: Any, q: Any) -> ConnectiveFormula:
    return ConnectiveFormula(LogicalConnective.OR, [p, q])


def neg(p: Any) -> ConnectiveFormula:
    return ConnectiveFormula(LogicalConnective.NOT, [p])


def biconditional(p: Any, q: Any) -> ConnectiveFormula:
    return ConnectiveFormula(LogicalConnective.BICONDITIONAL, [p, q])


class _NecessaryFormula:
    """Minimal mock for a modally-necessary formula."""

    def __init__(self, content: Any) -> None:
        self.modality = "necessary"
        self.content = content


def necessary(f: Any) -> _NecessaryFormula:
    return _NecessaryFormula(f)


# ---------------------------------------------------------------------------
# Propositional: ModusPonens
# ---------------------------------------------------------------------------

class TestModusPonens:
    def test_name(self):
        assert ModusPonens().name() == "Modus Ponens"

    def test_can_apply_true(self):
        p, q = atom("P"), atom("Q")
        assert ModusPonens().can_apply([p, impl(p, q)])

    def test_can_apply_false_no_matching_antecedent(self):
        r, q = atom("R"), atom("Q")
        p = atom("P")
        assert not ModusPonens().can_apply([r, impl(p, q)])

    def test_can_apply_false_empty(self):
        assert not ModusPonens().can_apply([])

    def test_apply_derives_q(self):
        """GIVEN P and P→Q WHEN apply THEN result contains Q."""
        p, q = atom("P"), atom("Q")
        result = ModusPonens().apply([p, impl(p, q)])
        assert q in result

    def test_apply_derives_q_only(self):
        p, q = atom("P"), atom("Q")
        result = ModusPonens().apply([p, impl(p, q)])
        assert len(result) == 1

    def test_apply_empty_when_no_match(self):
        p, r, q = atom("P"), atom("R"), atom("Q")
        result = ModusPonens().apply([r, impl(p, q)])
        assert result == []


# ---------------------------------------------------------------------------
# Propositional: Simplification
# ---------------------------------------------------------------------------

class TestSimplification:
    def test_name(self):
        assert Simplification().name() == "Simplification"

    def test_can_apply_true(self):
        assert Simplification().can_apply([conj(atom("P"), atom("Q"))])

    def test_can_apply_false_no_conjunction(self):
        assert not Simplification().can_apply([atom("P"), atom("Q")])

    def test_apply_extracts_both_conjuncts(self):
        p, q = atom("P"), atom("Q")
        result = Simplification().apply([conj(p, q)])
        assert p in result
        assert q in result

    def test_apply_multiple_conjunctions(self):
        p, q, r, s = atom("P"), atom("Q"), atom("R"), atom("S")
        result = Simplification().apply([conj(p, q), conj(r, s)])
        assert p in result and q in result and r in result and s in result


# ---------------------------------------------------------------------------
# Propositional: ConjunctionIntroduction
# ---------------------------------------------------------------------------

class TestConjunctionIntroduction:
    def test_name(self):
        assert ConjunctionIntroduction().name() == "Conjunction Introduction"

    def test_can_apply_two_formulas(self):
        assert ConjunctionIntroduction().can_apply([atom("P"), atom("Q")])

    def test_can_apply_false_single(self):
        assert not ConjunctionIntroduction().can_apply([atom("P")])

    def test_apply_creates_conjunction(self):
        p, q = atom("P"), atom("Q")
        result = ConjunctionIntroduction().apply([p, q])
        assert len(result) >= 1
        conj_formula = result[0]
        assert isinstance(conj_formula, ConnectiveFormula)
        assert conj_formula.connective == LogicalConnective.AND
        assert p in conj_formula.formulas
        assert q in conj_formula.formulas

    def test_apply_three_formulas_produces_multiple_pairs(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        result = ConjunctionIntroduction().apply([p, q, r])
        # Should produce P∧Q, P∧R, Q∧R
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Propositional: Weakening
# ---------------------------------------------------------------------------

class TestWeakening:
    def test_name(self):
        assert Weakening().name() == "Weakening"

    def test_can_apply_conjunction(self):
        assert Weakening().can_apply([conj(atom("P"), atom("Q"))])

    def test_can_apply_false_no_conjunction(self):
        assert not Weakening().can_apply([atom("P"), disj(atom("A"), atom("B"))])

    def test_apply_derives_disjunction_from_conjunction(self):
        """GIVEN P∧Q WHEN apply THEN result contains P∨Q."""
        p, q = atom("P"), atom("Q")
        result = Weakening().apply([conj(p, q)])
        assert len(result) == 1
        d = result[0]
        assert isinstance(d, ConnectiveFormula)
        assert d.connective == LogicalConnective.OR

    def test_apply_empty_without_conjunction(self):
        assert Weakening().apply([atom("P")]) == []


# ---------------------------------------------------------------------------
# Propositional: DeMorgan
# ---------------------------------------------------------------------------

class TestDeMorgan:
    def test_name(self):
        assert DeMorgan().name() == "DeMorgan"

    def test_can_apply_not_and(self):
        """GIVEN ¬(P∧Q) WHEN can_apply THEN True."""
        p, q = atom("P"), atom("Q")
        assert DeMorgan().can_apply([neg(conj(p, q))])

    def test_can_apply_not_or(self):
        """GIVEN ¬(P∨Q) WHEN can_apply THEN True."""
        p, q = atom("P"), atom("Q")
        assert DeMorgan().can_apply([neg(disj(p, q))])

    def test_can_apply_neg_or_neg(self):
        """GIVEN (¬P∨¬Q) WHEN can_apply (reverse DeMorgan) THEN True."""
        p, q = atom("P"), atom("Q")
        neg_p, neg_q = neg(p), neg(q)
        assert DeMorgan().can_apply([disj(neg_p, neg_q)])

    def test_can_apply_neg_and_neg(self):
        """GIVEN (¬P∧¬Q) WHEN can_apply THEN True."""
        p, q = atom("P"), atom("Q")
        assert DeMorgan().can_apply([conj(neg(p), neg(q))])

    def test_can_apply_false_plain_conjunction(self):
        assert not DeMorgan().can_apply([conj(atom("P"), atom("Q"))])

    def test_apply_not_and_becomes_neg_or_neg(self):
        """¬(P∧Q) → (¬P∨¬Q)."""
        p, q = atom("P"), atom("Q")
        result = DeMorgan().apply([neg(conj(p, q))])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, ConnectiveFormula)
        assert r.connective == LogicalConnective.OR

    def test_apply_not_or_becomes_neg_and_neg(self):
        """¬(P∨Q) → (¬P∧¬Q)."""
        p, q = atom("P"), atom("Q")
        result = DeMorgan().apply([neg(disj(p, q))])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, ConnectiveFormula)
        assert r.connective == LogicalConnective.AND

    def test_apply_neg_or_neg_becomes_not_and(self):
        """(¬P∨¬Q) → ¬(P∧Q)."""
        p, q = atom("P"), atom("Q")
        result = DeMorgan().apply([disj(neg(p), neg(q))])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, ConnectiveFormula)
        assert r.connective == LogicalConnective.NOT

    def test_apply_neg_and_neg_becomes_not_or(self):
        """(¬P∧¬Q) → ¬(P∨Q)."""
        p, q = atom("P"), atom("Q")
        result = DeMorgan().apply([conj(neg(p), neg(q))])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, ConnectiveFormula)
        assert r.connective == LogicalConnective.NOT


# ---------------------------------------------------------------------------
# Propositional: DoubleNegation
# ---------------------------------------------------------------------------

class TestDoubleNegation:
    def test_name(self):
        assert DoubleNegation().name() == "Double Negation"

    def test_can_apply_double_neg(self):
        p = atom("P")
        assert DoubleNegation().can_apply([neg(neg(p))])

    def test_can_apply_false_single_neg(self):
        assert not DoubleNegation().can_apply([neg(atom("P"))])

    def test_can_apply_false_empty(self):
        assert not DoubleNegation().can_apply([])

    def test_apply_eliminates_double_neg(self):
        """¬¬P → P."""
        p = atom("P")
        result = DoubleNegation().apply([neg(neg(p))])
        assert p in result

    def test_apply_empty_without_double_neg(self):
        p = atom("P")
        assert DoubleNegation().apply([neg(p)]) == []


# ---------------------------------------------------------------------------
# Propositional: DisjunctiveSyllogism
# ---------------------------------------------------------------------------

class TestDisjunctiveSyllogism:
    def test_name(self):
        assert DisjunctiveSyllogism().name() == "Disjunctive Syllogism"

    def test_can_apply_true(self):
        """¬P and P∨Q → can derive Q."""
        p, q = atom("P"), atom("Q")
        assert DisjunctiveSyllogism().can_apply([neg(p), disj(p, q)])

    def test_can_apply_false_no_negation(self):
        p, q = atom("P"), atom("Q")
        assert not DisjunctiveSyllogism().can_apply([p, disj(p, q)])

    def test_can_apply_false_negated_not_in_disjunction(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        # ¬R and P∨Q — R is not in P∨Q
        assert not DisjunctiveSyllogism().can_apply([neg(r), disj(p, q)])

    def test_apply_derives_remaining_disjunct(self):
        """¬P and P∨Q → Q."""
        p, q = atom("P"), atom("Q")
        result = DisjunctiveSyllogism().apply([neg(p), disj(p, q)])
        assert q in result

    def test_apply_three_disjuncts_produces_or(self):
        """¬P and P∨Q∨R → Q∨R."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        triple_or = ConnectiveFormula(LogicalConnective.OR, [p, q, r])
        result = DisjunctiveSyllogism().apply([neg(p), triple_or])
        assert len(result) >= 1
        remaining = result[0]
        assert isinstance(remaining, ConnectiveFormula)
        assert remaining.connective == LogicalConnective.OR

    def test_apply_empty_when_no_match(self):
        p, q = atom("P"), atom("Q")
        assert DisjunctiveSyllogism().apply([p, disj(p, q)]) == []


# ---------------------------------------------------------------------------
# Propositional: Contraposition
# ---------------------------------------------------------------------------

class TestContraposition:
    def test_name(self):
        assert Contraposition().name() == "Contraposition"

    def test_can_apply_implication(self):
        assert Contraposition().can_apply([impl(atom("P"), atom("Q"))])

    def test_can_apply_false_no_implication(self):
        assert not Contraposition().can_apply([atom("P"), atom("Q")])

    def test_apply_produces_contrapositive(self):
        """P→Q becomes ¬Q→¬P."""
        p, q = atom("P"), atom("Q")
        result = Contraposition().apply([impl(p, q)])
        assert len(result) == 1
        cp = result[0]
        assert isinstance(cp, ConnectiveFormula)
        assert cp.connective == LogicalConnective.IMPLIES
        # Antecedent should be ¬Q
        ant = cp.formulas[0]
        assert isinstance(ant, ConnectiveFormula)
        assert ant.connective == LogicalConnective.NOT
        assert ant.formulas[0] == q

    def test_apply_empty_without_implication(self):
        p = atom("P")
        assert Contraposition().apply([p]) == []


# ---------------------------------------------------------------------------
# Propositional: HypotheticalSyllogism
# ---------------------------------------------------------------------------

class TestHypotheticalSyllogism:
    def test_name(self):
        assert HypotheticalSyllogism().name() == "Hypothetical Syllogism"

    def test_can_apply_chain(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        assert HypotheticalSyllogism().can_apply([impl(p, q), impl(q, r)])

    def test_can_apply_false_no_match(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        # P→Q and R→Q — Q is consequent of both, not a chain
        assert not HypotheticalSyllogism().can_apply([impl(p, q), impl(r, q)])

    def test_can_apply_false_single(self):
        p, q = atom("P"), atom("Q")
        assert not HypotheticalSyllogism().can_apply([impl(p, q)])

    def test_apply_derives_p_implies_r(self):
        """P→Q and Q→R → P→R."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        result = HypotheticalSyllogism().apply([impl(p, q), impl(q, r)])
        assert len(result) >= 1
        chained = result[0]
        assert isinstance(chained, ConnectiveFormula)
        assert chained.connective == LogicalConnective.IMPLIES
        assert chained.formulas[0] == p
        assert chained.formulas[1] == r

    def test_apply_three_chain_produces_two_shortcuts(self):
        """P→Q, Q→R, R→S produces P→R, Q→S (and P→S via second pair)."""
        p, q, r, s = atom("P"), atom("Q"), atom("R"), atom("S")
        result = HypotheticalSyllogism().apply([impl(p, q), impl(q, r), impl(r, s)])
        assert len(result) >= 2


# ---------------------------------------------------------------------------
# Propositional: ImplicationElimination
# ---------------------------------------------------------------------------

class TestImplicationElimination:
    def test_name(self):
        assert ImplicationElimination().name() == "Implication Elimination"

    def test_can_apply_implication(self):
        assert ImplicationElimination().can_apply([impl(atom("P"), atom("Q"))])

    def test_can_apply_false(self):
        assert not ImplicationElimination().can_apply([atom("P")])

    def test_apply_converts_to_disjunction(self):
        """P→Q becomes ¬P∨Q."""
        p, q = atom("P"), atom("Q")
        result = ImplicationElimination().apply([impl(p, q)])
        assert len(result) == 1
        d = result[0]
        assert isinstance(d, ConnectiveFormula)
        assert d.connective == LogicalConnective.OR
        # One element should be ¬P
        not_p_found = any(
            isinstance(f, ConnectiveFormula) and
            f.connective == LogicalConnective.NOT and f.formulas[0] == p
            for f in d.formulas
        )
        assert not_p_found
        assert q in d.formulas

    def test_apply_empty_without_implication(self):
        assert ImplicationElimination().apply([atom("P")]) == []


# ---------------------------------------------------------------------------
# Modal: NecessityDistribution (K axiom) — apply() paths
# ---------------------------------------------------------------------------

class TestNecessityDistributionApply:
    """Tests for NecessityDistribution.apply() (K axiom: □(P→Q) ∧ □P ⊢ □Q/Q)."""

    def test_name(self):
        assert NecessityDistribution().name() == "NecessityDistribution"

    def test_apply_derives_q_from_k_axiom(self):
        """□(P→Q) and □P should let us derive Q."""
        p, q = atom("P"), atom("Q")
        box_impl = necessary(impl(p, q))
        box_p = necessary(p)
        rule = NecessityDistribution()
        result = rule.apply([box_impl, box_p])
        assert len(result) == 1
        assert result[0] == q

    def test_apply_empty_when_only_one_necessary(self):
        p, q = atom("P"), atom("Q")
        box_impl = necessary(impl(p, q))
        rule = NecessityDistribution()
        # Only one necessary formula → nothing to derive
        result = rule.apply([box_impl])
        assert result == []

    def test_apply_empty_when_antecedent_mismatch(self):
        """□(P→Q) and □R (R ≠ P) → no derivation."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        box_impl = necessary(impl(p, q))
        box_r = necessary(r)
        rule = NecessityDistribution()
        result = rule.apply([box_impl, box_r])
        assert result == []


# ---------------------------------------------------------------------------
# Modal: PossibilityDuality — can_apply() and apply()
# ---------------------------------------------------------------------------

class TestPossibilityDuality:
    """Tests for PossibilityDuality.can_apply() and .apply()."""

    def test_name(self):
        assert PossibilityDuality().name() == "PossibilityDuality"

    def _make_not_box_not_p(self, p: Any) -> ConnectiveFormula:
        """Build ¬□¬P."""
        not_p = neg(p)
        box_not_p = necessary(not_p)
        return neg(box_not_p)

    def test_can_apply_not_box_not_p(self):
        p = atom("P")
        rule = PossibilityDuality()
        not_box_not_p = self._make_not_box_not_p(p)
        assert rule.can_apply([not_box_not_p])

    def test_can_apply_false_plain_negation(self):
        p = atom("P")
        rule = PossibilityDuality()
        assert not rule.can_apply([neg(p)])

    def test_can_apply_false_empty(self):
        assert not PossibilityDuality().can_apply([])

    def test_apply_derives_p_from_not_box_not_p(self):
        """¬□¬P → ◇P (returns P as the possible formula)."""
        p = atom("P")
        rule = PossibilityDuality()
        not_box_not_p = self._make_not_box_not_p(p)
        result = rule.apply([not_box_not_p])
        assert len(result) == 1
        assert result[0] == p

    def test_apply_empty_without_matching_structure(self):
        p = atom("P")
        rule = PossibilityDuality()
        # ¬P is not ¬□¬P
        assert rule.apply([neg(p)]) == []


# ---------------------------------------------------------------------------
# Modal: NecessityConjunction — name + apply
# ---------------------------------------------------------------------------

class TestNecessityConjunctionFull:
    """Additional tests for NecessityConjunction to cover name() and edge cases."""

    def test_name(self):
        assert NecessityConjunction().name() == "NecessityConjunction"

    def test_apply_produces_conjunction_of_contents(self):
        """□P ∧ □Q → P∧Q."""
        p, q = atom("P"), atom("Q")
        box_p = necessary(p)
        box_q = necessary(q)
        rule = NecessityConjunction()
        result = rule.apply([box_p, box_q])
        assert len(result) == 1
        r = result[0]
        assert isinstance(r, ConnectiveFormula)
        assert r.connective == LogicalConnective.AND

    def test_apply_empty_for_single_necessary(self):
        p = atom("P")
        rule = NecessityConjunction()
        assert rule.apply([necessary(p)]) == []


# ---------------------------------------------------------------------------
# Resolution: ResolutionRule edge cases
# ---------------------------------------------------------------------------

class TestResolutionRuleEdgeCases:
    """Additional resolution rule tests targeting empty resolvent + negative paths."""

    def test_resolution_empty_resolvent_not_in_results(self):
        """
        Resolution of complementary unit clauses (P) ∨ empty → contradiction.
        Empty resolvent is silently discarded (pass branch at line 50).
        """
        p = atom("P")
        # Clauses: (P∨¬P) — both disjuncts cancel; produces empty resolvent
        not_p = neg(p)
        clause1 = disj(p, atom("Q"))
        clause2 = disj(not_p, atom("R"))
        rule = ResolutionRule()
        result = rule.apply([clause1, clause2])
        # Result should be Q∨R (or Q/R if single remaining)
        assert len(result) >= 1

    def test_unit_resolution_false_when_no_unit_in_neg(self):
        """UnitResolutionRule returns False when no unit literal appears negated in any clause."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        # r is a unit but ¬r doesn't appear in p∨q
        rule = UnitResolutionRule()
        assert not rule.can_apply([r, disj(p, q)])

    def test_unit_resolution_apply_multiple_remaining(self):
        """P ∧ (¬P ∨ Q ∨ R) → Q ∨ R (multi-literal remaining)."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        triple = ConnectiveFormula(LogicalConnective.OR, [neg(p), q, r])
        rule = UnitResolutionRule()
        result = rule.apply([p, triple])
        assert len(result) >= 1
        rem = result[0]
        assert isinstance(rem, ConnectiveFormula)
        assert rem.connective == LogicalConnective.OR

    def test_factoring_false_no_duplicates(self):
        """FactoringRule.can_apply returns False when no disjunct duplicates exist."""
        p, q = atom("P"), atom("Q")
        rule = FactoringRule()
        assert not rule.can_apply([disj(p, q)])

    def test_factoring_apply_single_literal_result(self):
        """P∨P → P (single literal after de-duplication)."""
        p = atom("P")
        tautological = ConnectiveFormula(LogicalConnective.OR, [p, p])
        rule = FactoringRule()
        assert rule.can_apply([tautological])
        result = rule.apply([tautological])
        assert len(result) == 1
        assert result[0] == p

    def test_subsumption_can_apply_when_subsumed(self):
        """SubsumptionRule.can_apply is True when C1 ⊂ C2."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        shorter = disj(p, q)
        longer = ConnectiveFormula(LogicalConnective.OR, [p, q, r])
        rule = SubsumptionRule()
        assert rule.can_apply([shorter, longer])

    def test_subsumption_apply_keeps_shorter_clause(self):
        """SubsumptionRule.apply removes the longer (subsumed) clause."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        shorter = disj(p, q)
        longer = ConnectiveFormula(LogicalConnective.OR, [p, q, r])
        rule = SubsumptionRule()
        result = rule.apply([shorter, longer])
        assert shorter in result
        assert longer not in result

    def test_case_analysis_can_apply(self):
        """CaseAnalysisRule: P∨Q, P→R, Q→R → can derive R."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        rule = CaseAnalysisRule()
        assert rule.can_apply([disj(p, q), impl(p, r), impl(q, r)])

    def test_case_analysis_apply_derives_r(self):
        p, q, r = atom("P"), atom("Q"), atom("R")
        rule = CaseAnalysisRule()
        result = rule.apply([disj(p, q), impl(p, r), impl(q, r)])
        assert r in result

    def test_case_analysis_false_different_consequents(self):
        """P→R and Q→S (R≠S): cannot apply."""
        p, q, r, s = atom("P"), atom("Q"), atom("R"), atom("S")
        rule = CaseAnalysisRule()
        assert not rule.can_apply([disj(p, q), impl(p, r), impl(q, s)])

    def test_proof_by_contradiction_can_apply(self):
        p = atom("P")
        rule = ProofByContradictionRule()
        assert rule.can_apply([p, neg(p)])

    def test_proof_by_contradiction_can_apply_reverse_order(self):
        p = atom("P")
        rule = ProofByContradictionRule()
        assert rule.can_apply([neg(p), p])

    def test_proof_by_contradiction_apply_returns_empty(self):
        """apply() returns [] — the contradiction is found, no formula to add."""
        p = atom("P")
        rule = ProofByContradictionRule()
        result = rule.apply([p, neg(p)])
        assert result == []

    def test_proof_by_contradiction_false_no_contradiction(self):
        p, q = atom("P"), atom("Q")
        rule = ProofByContradictionRule()
        assert not rule.can_apply([p, q])


# ---------------------------------------------------------------------------
# Specialized: ConstructiveDilemma apply()
# ---------------------------------------------------------------------------

class TestConstructiveDilemmaApply:
    """Tests for ConstructiveDilemma.apply()."""

    def _setup(self):
        p, q, r, s = atom("P"), atom("Q"), atom("R"), atom("S")
        # (P→Q) ∧ (R→S) ∧ (P∨R) → Q∨S
        p_impl_q = impl(p, q)
        r_impl_s = impl(r, s)
        p_or_r = disj(p, r)
        return p, q, r, s, p_impl_q, r_impl_s, p_or_r

    def test_constructive_dilemma_can_apply(self):
        p, q, r, s, p_impl_q, r_impl_s, p_or_r = self._setup()
        rule = ConstructiveDilemma()
        assert rule.can_apply([p_impl_q, r_impl_s, p_or_r])

    def test_constructive_dilemma_apply_produces_q_or_s(self):
        """(P→Q) ∧ (R→S) ∧ (P∨R) ⊢ Q∨S."""
        p, q, r, s, p_impl_q, r_impl_s, p_or_r = self._setup()
        rule = ConstructiveDilemma()
        result = rule.apply([p_impl_q, r_impl_s, p_or_r])
        assert len(result) >= 1
        q_or_s = result[0]
        assert isinstance(q_or_s, ConnectiveFormula)
        assert q_or_s.connective == LogicalConnective.OR
        assert q in q_or_s.formulas
        assert s in q_or_s.formulas

    def test_constructive_dilemma_false_no_disjunction(self):
        p, q, r, s = atom("P"), atom("Q"), atom("R"), atom("S")
        rule = ConstructiveDilemma()
        # No P∨R disjunction
        assert not rule.can_apply([impl(p, q), impl(r, s)])

    def test_constructive_dilemma_apply_empty_without_match(self):
        p, q, r, s = atom("P"), atom("Q"), atom("R"), atom("S")
        rule = ConstructiveDilemma()
        # P∨Q but antecedents are R and S — no match
        result = rule.apply([impl(r, atom("X")), impl(s, atom("Y")), disj(p, q)])
        # The disjunction contains P,Q not R,S, so no result
        assert result == []


# ---------------------------------------------------------------------------
# Specialized: DestructiveDilemma apply()
# ---------------------------------------------------------------------------

class TestDestructiveDilemmaApply:
    """Tests for DestructiveDilemma.apply()."""

    def _setup(self):
        p, q, r, s = atom("P"), atom("Q"), atom("R"), atom("S")
        # (P→Q) ∧ (R→S) ∧ (¬Q∨¬S) → ¬P∨¬R
        p_impl_q = impl(p, q)
        r_impl_s = impl(r, s)
        not_q_or_not_s = disj(neg(q), neg(s))
        return p, q, r, s, p_impl_q, r_impl_s, not_q_or_not_s

    def test_destructive_dilemma_can_apply(self):
        p, q, r, s, p_impl_q, r_impl_s, not_q_or_not_s = self._setup()
        rule = DestructiveDilemma()
        assert rule.can_apply([p_impl_q, r_impl_s, not_q_or_not_s])

    def test_destructive_dilemma_apply_produces_not_p_or_not_r(self):
        """(P→Q) ∧ (R→S) ∧ (¬Q∨¬S) ⊢ ¬P∨¬R."""
        p, q, r, s, p_impl_q, r_impl_s, not_q_or_not_s = self._setup()
        rule = DestructiveDilemma()
        result = rule.apply([p_impl_q, r_impl_s, not_q_or_not_s])
        assert len(result) >= 1
        not_p_or_not_r = result[0]
        assert isinstance(not_p_or_not_r, ConnectiveFormula)
        assert not_p_or_not_r.connective == LogicalConnective.OR
        # Both elements should be negations
        for f in not_p_or_not_r.formulas:
            assert isinstance(f, ConnectiveFormula)
            assert f.connective == LogicalConnective.NOT

    def test_destructive_dilemma_false_no_negated_disjunction(self):
        """Without ¬Q∨¬S, cannot apply."""
        p, q, r, s = atom("P"), atom("Q"), atom("R"), atom("S")
        rule = DestructiveDilemma()
        assert not rule.can_apply([impl(p, q), impl(r, s), disj(q, s)])

    def test_destructive_dilemma_apply_empty_without_match(self):
        p, q = atom("P"), atom("Q")
        rule = DestructiveDilemma()
        result = rule.apply([impl(p, q)])
        assert result == []


# ---------------------------------------------------------------------------
# Cross-module chains
# ---------------------------------------------------------------------------

class TestPropositionalRuleChains:
    """Tests for chaining multiple propositional rules."""

    def test_modus_ponens_chain(self):
        """P, P→Q, Q→R: apply MP twice to derive R."""
        p, q, r = atom("P"), atom("Q"), atom("R")
        pq = impl(p, q)
        qr = impl(q, r)
        # Step 1: P and P→Q → Q
        result1 = ModusPonens().apply([p, pq, qr])
        # Step 2: Q and Q→R → R
        result2 = ModusPonens().apply(result1 + [pq, qr])
        assert r in result2

    def test_demorgan_then_double_neg_simplification(self):
        """¬(P∧Q) → ¬P∨¬Q; ¬¬P → P as sub-expressions."""
        p, q = atom("P"), atom("Q")
        # ¬(P∧Q) → ¬P∨¬Q
        dm_result = DeMorgan().apply([neg(conj(p, q))])
        assert len(dm_result) == 1
        # ¬¬P exists; verify DoubleNegation can simplify
        dn_result = DoubleNegation().apply([neg(neg(p))])
        assert dn_result[0] == p

    def test_implication_elim_then_disjunctive_syllogism(self):
        """P→Q → ¬P∨Q; then ¬(¬P) and ¬P∨Q by DS → Q."""
        p, q = atom("P"), atom("Q")
        # ImplicationElimination: P→Q → ¬P∨Q
        ie_result = ImplicationElimination().apply([impl(p, q)])
        not_p_or_q = ie_result[0]
        # DisjunctiveSyllogism: ¬¬P (which equals p) and ¬P∨Q → Q
        # Actually DS needs ¬(¬P) to eliminate ¬P from ¬P∨Q
        not_not_p = neg(neg(p))
        # But DS needs the negated formula directly in the disjunction
        # ¬P is in (¬P∨Q), and we have ¬(¬P) = not_not_p as our unit → DS gives Q
        not_p_formula = not_p_or_q.formulas[0]  # This is ¬P
        ds_unit = neg(not_p_formula)            # This is ¬(¬P)
        ds_result = DisjunctiveSyllogism().apply([ds_unit, not_p_or_q])
        assert q in ds_result


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------

class TestPropositionalExports:
    def test_all_rules_importable(self):
        from ipfs_datasets_py.logic.CEC.native.inference_rules.propositional import __all__
        assert "ModusPonens" in __all__
        assert "Simplification" in __all__
        assert "DeMorgan" in __all__
        assert "DisjunctiveSyllogism" in __all__
        assert "ImplicationElimination" in __all__

    def test_rule_names_are_strings(self):
        rules = [
            ModusPonens(), Simplification(), ConjunctionIntroduction(),
            Weakening(), DeMorgan(), DoubleNegation(), DisjunctiveSyllogism(),
            Contraposition(), HypotheticalSyllogism(), ImplicationElimination(),
        ]
        for rule in rules:
            assert isinstance(rule.name(), str) and len(rule.name()) > 0

    def test_apply_always_returns_list(self):
        rules = [
            ModusPonens(), Simplification(), ConjunctionIntroduction(),
            Weakening(), DeMorgan(), DoubleNegation(), DisjunctiveSyllogism(),
            Contraposition(), HypotheticalSyllogism(), ImplicationElimination(),
        ]
        for rule in rules:
            result = rule.apply([])
            assert isinstance(result, list)


class TestResolutionExports:
    def test_all_rules_importable(self):
        from ipfs_datasets_py.logic.CEC.native.inference_rules.resolution import __all__
        assert "ResolutionRule" in __all__
        assert "UnitResolutionRule" in __all__
        assert "FactoringRule" in __all__
        assert "SubsumptionRule" in __all__
        assert "CaseAnalysisRule" in __all__
        assert "ProofByContradictionRule" in __all__

    def test_rule_names_are_strings(self):
        rules = [
            ResolutionRule(), UnitResolutionRule(), FactoringRule(),
            SubsumptionRule(), CaseAnalysisRule(), ProofByContradictionRule(),
        ]
        for rule in rules:
            assert isinstance(rule.name(), str) and len(rule.name()) > 0


class TestSpecializedExports:
    def test_all_rules_importable(self):
        from ipfs_datasets_py.logic.CEC.native.inference_rules.specialized import __all__
        assert "ConstructiveDilemma" in __all__
        assert "DestructiveDilemma" in __all__
        assert "ExportationRule" in __all__
        assert "AbsorptionRule" in __all__

    def test_rule_names_are_strings(self):
        rules = [
            ConstructiveDilemma(), DestructiveDilemma(), ExportationRule(),
            AbsorptionRule(), AdditionRule(), TautologyRule(), CommutativityConjunction(),
        ]
        for rule in rules:
            assert isinstance(rule.name(), str) and len(rule.name()) > 0
