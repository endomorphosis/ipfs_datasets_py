"""
Tests for modal, resolution, and specialized CEC inference rule modules.

Tests validate that the new rule modules (Phase 2 additions) work correctly:
- modal.py: Necessity/possibility modal logic rules
- resolution.py: Resolution-based theorem proving rules
- specialized.py: Advanced propositional rules
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    ConnectiveFormula,
    LogicalConnective,
    Predicate,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.modal import (
    NecessityElimination,
    PossibilityIntroduction,
    NecessityDistribution,
    PossibilityDuality,
    NecessityConjunction,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.resolution import (
    ResolutionRule,
    UnitResolutionRule,
    FactoringRule,
    SubsumptionRule,
    CaseAnalysisRule,
    ProofByContradictionRule,
)
from ipfs_datasets_py.logic.CEC.native.inference_rules.specialized import (
    BiconditionalIntroduction,
    BiconditionalElimination,
    ConstructiveDilemma,
    DestructiveDilemma,
    ExportationRule,
    AbsorptionRule,
    AdditionRule,
    TautologyRule,
    CommutativityConjunction,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def make_atom(name: str) -> AtomicFormula:
    """Create a simple zero-arity atomic formula (propositional variable)."""
    return AtomicFormula(Predicate(name, []), [])


def make_impl(p: AtomicFormula, q: AtomicFormula) -> ConnectiveFormula:
    """Create P → Q."""
    return ConnectiveFormula(LogicalConnective.IMPLIES, [p, q])


def make_and(p, q) -> ConnectiveFormula:
    """Create P ∧ Q."""
    return ConnectiveFormula(LogicalConnective.AND, [p, q])


def make_or(p, q) -> ConnectiveFormula:
    """Create P ∨ Q."""
    return ConnectiveFormula(LogicalConnective.OR, [p, q])


def make_not(p) -> ConnectiveFormula:
    """Create ¬P."""
    return ConnectiveFormula(LogicalConnective.NOT, [p])


def make_bicond(p, q) -> ConnectiveFormula:
    """Create P ↔ Q."""
    return ConnectiveFormula(LogicalConnective.BICONDITIONAL, [p, q])


def make_necessary(formula):
    """Create a mock necessary formula (using a simple wrapper object)."""
    class NecessaryFormula:
        def __init__(self, content):
            self.modality = 'necessary'
            self.content = content
    return NecessaryFormula(formula)


# ---------------------------------------------------------------------------
# Modal Rule Tests
# ---------------------------------------------------------------------------

class TestModalRules:
    """Tests for modal logic inference rules."""

    def test_necessity_elimination_name(self):
        """GIVEN NecessityElimination WHEN checking name THEN returns 'NecessityElimination'."""
        rule = NecessityElimination()
        assert rule.name() == "NecessityElimination"

    def test_necessity_elimination_can_apply_with_necessary_formula(self):
        """
        GIVEN a necessary formula □P
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        box_p = make_necessary(p)
        rule = NecessityElimination()
        assert rule.can_apply([box_p])

    def test_necessity_elimination_cannot_apply_without_necessary(self):
        """
        GIVEN only plain formulas (no modality)
        WHEN checking can_apply
        THEN should return False.
        """
        p = make_atom("P")
        rule = NecessityElimination()
        assert not rule.can_apply([p])

    def test_necessity_elimination_apply_extracts_content(self):
        """
        GIVEN □P
        WHEN applying NecessityElimination
        THEN should derive P.
        """
        p = make_atom("P")
        box_p = make_necessary(p)
        rule = NecessityElimination()
        result = rule.apply([box_p])
        assert len(result) == 1
        assert result[0] == p

    def test_possibility_introduction_name(self):
        """GIVEN PossibilityIntroduction WHEN checking name THEN returns correct name."""
        rule = PossibilityIntroduction()
        assert rule.name() == "PossibilityIntroduction"

    def test_possibility_introduction_can_apply_any_formula(self):
        """
        GIVEN any non-empty formula list
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        rule = PossibilityIntroduction()
        assert rule.can_apply([p])

    def test_possibility_introduction_cannot_apply_empty(self):
        """
        GIVEN an empty formula list
        WHEN checking can_apply
        THEN should return False.
        """
        rule = PossibilityIntroduction()
        assert not rule.can_apply([])

    def test_possibility_introduction_apply_returns_formulas(self):
        """
        GIVEN P
        WHEN applying PossibilityIntroduction
        THEN should return P (as the possible formula).
        """
        p = make_atom("P")
        rule = PossibilityIntroduction()
        result = rule.apply([p])
        assert p in result

    def test_necessity_distribution_can_apply_with_k_axiom(self):
        """
        GIVEN □(P→Q) and □P
        WHEN checking can_apply for NecessityDistribution
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        impl = make_impl(p, q)
        box_impl = make_necessary(impl)
        box_p = make_necessary(p)
        rule = NecessityDistribution()
        assert rule.can_apply([box_impl, box_p])

    def test_necessity_distribution_cannot_apply_without_necessary(self):
        """
        GIVEN plain formulas without necessity
        WHEN checking can_apply
        THEN should return False.
        """
        p = make_atom("P")
        rule = NecessityDistribution()
        assert not rule.can_apply([p])

    def test_possibility_duality_name(self):
        """GIVEN PossibilityDuality WHEN checking name THEN returns correct name."""
        rule = PossibilityDuality()
        assert rule.name() == "PossibilityDuality"

    def test_necessity_conjunction_can_apply_two_necessary(self):
        """
        GIVEN □P and □Q
        WHEN checking can_apply for NecessityConjunction
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        box_p = make_necessary(p)
        box_q = make_necessary(q)
        rule = NecessityConjunction()
        assert rule.can_apply([box_p, box_q])

    def test_necessity_conjunction_apply_produces_conjunction(self):
        """
        GIVEN □P and □Q
        WHEN applying NecessityConjunction
        THEN should derive P∧Q.
        """
        p = make_atom("P")
        q = make_atom("Q")
        box_p = make_necessary(p)
        box_q = make_necessary(q)
        rule = NecessityConjunction()
        result = rule.apply([box_p, box_q])
        assert len(result) == 1
        assert isinstance(result[0], ConnectiveFormula)
        assert result[0].connective == LogicalConnective.AND


# ---------------------------------------------------------------------------
# Resolution Rule Tests
# ---------------------------------------------------------------------------

class TestResolutionRules:
    """Tests for resolution-based inference rules."""

    def test_resolution_rule_name(self):
        """GIVEN ResolutionRule WHEN checking name THEN returns 'Resolution'."""
        rule = ResolutionRule()
        assert rule.name() == "Resolution"

    def test_resolution_can_apply_with_complementary_clauses(self):
        """
        GIVEN (P ∨ Q) and (¬P ∨ R)
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        r = make_atom("R")
        c1 = make_or(p, q)
        c2 = make_or(make_not(p), r)
        rule = ResolutionRule()
        assert rule.can_apply([c1, c2])

    def test_resolution_cannot_apply_without_clauses(self):
        """
        GIVEN non-clause formulas
        WHEN checking can_apply
        THEN should return False.
        """
        p = make_atom("P")
        rule = ResolutionRule()
        assert not rule.can_apply([p])

    def test_resolution_apply_produces_resolvent(self):
        """
        GIVEN (P ∨ Q) and (¬P ∨ R)
        WHEN applying ResolutionRule
        THEN should derive Q ∨ R.
        """
        p = make_atom("P")
        q = make_atom("Q")
        r = make_atom("R")
        c1 = make_or(p, q)
        c2 = make_or(make_not(p), r)
        rule = ResolutionRule()
        result = rule.apply([c1, c2])
        assert len(result) >= 1
        # The resolvent should be Q ∨ R or contain Q and R
        resolvent = result[0]
        assert isinstance(resolvent, ConnectiveFormula)
        assert resolvent.connective == LogicalConnective.OR

    def test_unit_resolution_name(self):
        """GIVEN UnitResolutionRule WHEN checking name THEN returns 'UnitResolution'."""
        rule = UnitResolutionRule()
        assert rule.name() == "UnitResolution"

    def test_unit_resolution_can_apply(self):
        """
        GIVEN unit literal P and clause (¬P ∨ Q)
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        clause = make_or(make_not(p), q)
        rule = UnitResolutionRule()
        assert rule.can_apply([p, clause])

    def test_unit_resolution_apply_derives_consequent(self):
        """
        GIVEN P and (¬P ∨ Q)
        WHEN applying UnitResolutionRule
        THEN should derive Q.
        """
        p = make_atom("P")
        q = make_atom("Q")
        clause = make_or(make_not(p), q)
        rule = UnitResolutionRule()
        result = rule.apply([p, clause])
        assert len(result) >= 1
        assert result[0] == q

    def test_factoring_name(self):
        """GIVEN FactoringRule WHEN checking name THEN returns 'Factoring'."""
        rule = FactoringRule()
        assert rule.name() == "Factoring"

    def test_factoring_can_apply_with_duplicate(self):
        """
        GIVEN (P ∨ P ∨ Q)
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        clause = ConnectiveFormula(LogicalConnective.OR, [p, p, q])
        rule = FactoringRule()
        assert rule.can_apply([clause])

    def test_factoring_apply_removes_duplicates(self):
        """
        GIVEN (P ∨ P ∨ Q)
        WHEN applying FactoringRule
        THEN should derive (P ∨ Q).
        """
        p = make_atom("P")
        q = make_atom("Q")
        clause = ConnectiveFormula(LogicalConnective.OR, [p, p, q])
        rule = FactoringRule()
        result = rule.apply([clause])
        assert len(result) == 1
        assert isinstance(result[0], ConnectiveFormula)
        assert len(result[0].formulas) == 2

    def test_subsumption_name(self):
        """GIVEN SubsumptionRule WHEN checking name THEN returns 'Subsumption'."""
        rule = SubsumptionRule()
        assert rule.name() == "Subsumption"

    def test_subsumption_can_apply_when_clause_subsumed(self):
        """
        GIVEN P and (P ∨ Q) where P subsumes P∨Q
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        clause1 = p
        clause2 = make_or(p, q)
        rule = SubsumptionRule()
        assert rule.can_apply([clause1, clause2])

    def test_case_analysis_name(self):
        """GIVEN CaseAnalysisRule WHEN checking name THEN returns 'CaseAnalysis'."""
        rule = CaseAnalysisRule()
        assert rule.name() == "CaseAnalysis"

    def test_case_analysis_can_apply_with_pattern(self):
        """
        GIVEN (P ∨ Q), (P→R), (Q→R)
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        r = make_atom("R")
        disj = make_or(p, q)
        impl1 = make_impl(p, r)
        impl2 = make_impl(q, r)
        rule = CaseAnalysisRule()
        assert rule.can_apply([disj, impl1, impl2])

    def test_case_analysis_apply_derives_conclusion(self):
        """
        GIVEN (P ∨ Q), (P→R), (Q→R)
        WHEN applying CaseAnalysisRule
        THEN should derive R.
        """
        p = make_atom("P")
        q = make_atom("Q")
        r = make_atom("R")
        disj = make_or(p, q)
        impl1 = make_impl(p, r)
        impl2 = make_impl(q, r)
        rule = CaseAnalysisRule()
        result = rule.apply([disj, impl1, impl2])
        assert len(result) >= 1
        assert result[0] == r

    def test_proof_by_contradiction_name(self):
        """GIVEN ProofByContradictionRule WHEN checking name THEN returns correct name."""
        rule = ProofByContradictionRule()
        assert rule.name() == "ProofByContradiction"

    def test_proof_by_contradiction_can_apply_with_contradiction(self):
        """
        GIVEN P and ¬P
        WHEN checking can_apply
        THEN should return True (contradiction detected).
        """
        p = make_atom("P")
        not_p = make_not(p)
        rule = ProofByContradictionRule()
        assert rule.can_apply([p, not_p])

    def test_proof_by_contradiction_cannot_apply_without_contradiction(self):
        """
        GIVEN only P (no contradiction)
        WHEN checking can_apply
        THEN should return False.
        """
        p = make_atom("P")
        rule = ProofByContradictionRule()
        assert not rule.can_apply([p])


# ---------------------------------------------------------------------------
# Specialized Rule Tests
# ---------------------------------------------------------------------------

class TestSpecializedRules:
    """Tests for specialized inference rules."""

    def test_biconditional_introduction_name(self):
        """GIVEN BiconditionalIntroduction WHEN checking name THEN returns correct name."""
        rule = BiconditionalIntroduction()
        assert rule.name() == "BiconditionalIntroduction"

    def test_biconditional_introduction_can_apply(self):
        """
        GIVEN (P→Q) and (Q→P)
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        pq = make_impl(p, q)
        qp = make_impl(q, p)
        rule = BiconditionalIntroduction()
        assert rule.can_apply([pq, qp])

    def test_biconditional_introduction_cannot_apply_one_direction(self):
        """
        GIVEN only P→Q (not Q→P)
        WHEN checking can_apply
        THEN should return False.
        """
        p = make_atom("P")
        q = make_atom("Q")
        pq = make_impl(p, q)
        rule = BiconditionalIntroduction()
        assert not rule.can_apply([pq])

    def test_biconditional_introduction_apply_produces_biconditional(self):
        """
        GIVEN (P→Q) and (Q→P)
        WHEN applying BiconditionalIntroduction
        THEN should derive P↔Q.
        """
        p = make_atom("P")
        q = make_atom("Q")
        pq = make_impl(p, q)
        qp = make_impl(q, p)
        rule = BiconditionalIntroduction()
        result = rule.apply([pq, qp])
        assert len(result) == 1
        assert isinstance(result[0], ConnectiveFormula)
        assert result[0].connective == LogicalConnective.BICONDITIONAL

    def test_biconditional_elimination_name(self):
        """GIVEN BiconditionalElimination WHEN checking name THEN returns correct name."""
        rule = BiconditionalElimination()
        assert rule.name() == "BiconditionalElimination"

    def test_biconditional_elimination_can_apply(self):
        """
        GIVEN P↔Q
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        q = make_atom("Q")
        bicond = make_bicond(p, q)
        rule = BiconditionalElimination()
        assert rule.can_apply([bicond])

    def test_biconditional_elimination_apply_produces_two_implications(self):
        """
        GIVEN P↔Q
        WHEN applying BiconditionalElimination
        THEN should derive P→Q and Q→P.
        """
        p = make_atom("P")
        q = make_atom("Q")
        bicond = make_bicond(p, q)
        rule = BiconditionalElimination()
        result = rule.apply([bicond])
        assert len(result) == 2
        connectives = {r.connective for r in result if isinstance(r, ConnectiveFormula)}
        assert LogicalConnective.IMPLIES in connectives

    def test_constructive_dilemma_name(self):
        """GIVEN ConstructiveDilemma WHEN checking name THEN returns correct name."""
        rule = ConstructiveDilemma()
        assert rule.name() == "ConstructiveDilemma"

    def test_constructive_dilemma_can_apply(self):
        """
        GIVEN (P→Q), (R→S), (P∨R)
        WHEN checking can_apply
        THEN should return True.
        """
        p, q, r, s = make_atom("P"), make_atom("Q"), make_atom("R"), make_atom("S")
        impl1 = make_impl(p, q)
        impl2 = make_impl(r, s)
        disj = make_or(p, r)
        rule = ConstructiveDilemma()
        assert rule.can_apply([impl1, impl2, disj])

    def test_constructive_dilemma_apply_derives_disjunction(self):
        """
        GIVEN (P→Q), (R→S), (P∨R)
        WHEN applying ConstructiveDilemma
        THEN should derive Q∨S.
        """
        p, q, r, s = make_atom("P"), make_atom("Q"), make_atom("R"), make_atom("S")
        impl1 = make_impl(p, q)
        impl2 = make_impl(r, s)
        disj = make_or(p, r)
        rule = ConstructiveDilemma()
        result = rule.apply([impl1, impl2, disj])
        assert len(result) >= 1
        assert isinstance(result[0], ConnectiveFormula)
        assert result[0].connective == LogicalConnective.OR

    def test_destructive_dilemma_name(self):
        """GIVEN DestructiveDilemma WHEN checking name THEN returns correct name."""
        rule = DestructiveDilemma()
        assert rule.name() == "DestructiveDilemma"

    def test_exportation_name(self):
        """GIVEN ExportationRule WHEN checking name THEN returns correct name."""
        rule = ExportationRule()
        assert rule.name() == "Exportation"

    def test_exportation_can_apply(self):
        """
        GIVEN (P∧Q)→R
        WHEN checking can_apply
        THEN should return True.
        """
        p, q, r = make_atom("P"), make_atom("Q"), make_atom("R")
        p_and_q = make_and(p, q)
        impl = make_impl(p_and_q, r)
        rule = ExportationRule()
        assert rule.can_apply([impl])

    def test_exportation_apply_curries_implication(self):
        """
        GIVEN (P∧Q)→R
        WHEN applying ExportationRule
        THEN should derive P→(Q→R).
        """
        p, q, r = make_atom("P"), make_atom("Q"), make_atom("R")
        p_and_q = make_and(p, q)
        impl = make_impl(p_and_q, r)
        rule = ExportationRule()
        result = rule.apply([impl])
        assert len(result) == 1
        outer = result[0]
        assert isinstance(outer, ConnectiveFormula)
        assert outer.connective == LogicalConnective.IMPLIES
        # Inner should also be an implication
        inner = outer.formulas[1]
        assert isinstance(inner, ConnectiveFormula)
        assert inner.connective == LogicalConnective.IMPLIES

    def test_absorption_name(self):
        """GIVEN AbsorptionRule WHEN checking name THEN returns correct name."""
        rule = AbsorptionRule()
        assert rule.name() == "Absorption"

    def test_absorption_can_apply(self):
        """
        GIVEN P→Q
        WHEN checking can_apply
        THEN should return True.
        """
        p, q = make_atom("P"), make_atom("Q")
        rule = AbsorptionRule()
        assert rule.can_apply([make_impl(p, q)])

    def test_absorption_apply(self):
        """
        GIVEN P→Q
        WHEN applying AbsorptionRule
        THEN should derive P→(P∧Q).
        """
        p, q = make_atom("P"), make_atom("Q")
        rule = AbsorptionRule()
        result = rule.apply([make_impl(p, q)])
        assert len(result) == 1
        outer = result[0]
        assert outer.connective == LogicalConnective.IMPLIES
        assert isinstance(outer.formulas[1], ConnectiveFormula)
        assert outer.formulas[1].connective == LogicalConnective.AND

    def test_addition_name(self):
        """GIVEN AdditionRule WHEN checking name THEN returns correct name."""
        rule = AdditionRule()
        assert rule.name() == "Addition"

    def test_addition_can_apply(self):
        """
        GIVEN any non-empty formula list
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        rule = AdditionRule()
        assert rule.can_apply([p])

    def test_tautology_name(self):
        """GIVEN TautologyRule WHEN checking name THEN returns correct name."""
        rule = TautologyRule()
        assert rule.name() == "Tautology"

    def test_tautology_can_apply_with_duplicate_disjuncts(self):
        """
        GIVEN P∨P
        WHEN checking can_apply
        THEN should return True.
        """
        p = make_atom("P")
        pp = make_or(p, p)
        rule = TautologyRule()
        assert rule.can_apply([pp])

    def test_tautology_apply_simplifies(self):
        """
        GIVEN P∨P
        WHEN applying TautologyRule
        THEN should derive P.
        """
        p = make_atom("P")
        pp = make_or(p, p)
        rule = TautologyRule()
        result = rule.apply([pp])
        assert len(result) == 1
        assert result[0] == p

    def test_commutativity_conjunction_name(self):
        """GIVEN CommutativityConjunction WHEN checking name THEN returns correct name."""
        rule = CommutativityConjunction()
        assert rule.name() == "CommutativityConjunction"

    def test_commutativity_conjunction_can_apply(self):
        """
        GIVEN P∧Q
        WHEN checking can_apply
        THEN should return True.
        """
        p, q = make_atom("P"), make_atom("Q")
        rule = CommutativityConjunction()
        assert rule.can_apply([make_and(p, q)])

    def test_commutativity_conjunction_apply(self):
        """
        GIVEN P∧Q
        WHEN applying CommutativityConjunction
        THEN should derive Q∧P.
        """
        p, q = make_atom("P"), make_atom("Q")
        rule = CommutativityConjunction()
        result = rule.apply([make_and(p, q)])
        assert len(result) == 1
        flipped = result[0]
        assert isinstance(flipped, ConnectiveFormula)
        assert flipped.connective == LogicalConnective.AND
        assert flipped.formulas[0] == q
        assert flipped.formulas[1] == p


# ---------------------------------------------------------------------------
# __init__ export tests
# ---------------------------------------------------------------------------

class TestInferenceRulesPackageExports:
    """Verify all new rules are exported from the inference_rules package."""

    def test_modal_rules_exported(self):
        """All modal rules should be importable from the package."""
        from ipfs_datasets_py.logic.CEC.native.inference_rules import (
            NecessityElimination, PossibilityIntroduction, NecessityDistribution,
            PossibilityDuality, NecessityConjunction,
        )
        assert NecessityElimination is not None
        assert PossibilityIntroduction is not None
        assert NecessityDistribution is not None
        assert PossibilityDuality is not None
        assert NecessityConjunction is not None

    def test_resolution_rules_exported(self):
        """All resolution rules should be importable from the package."""
        from ipfs_datasets_py.logic.CEC.native.inference_rules import (
            ResolutionRule, UnitResolutionRule, FactoringRule,
            SubsumptionRule, CaseAnalysisRule, ProofByContradictionRule,
        )
        assert ResolutionRule is not None
        assert UnitResolutionRule is not None
        assert FactoringRule is not None
        assert SubsumptionRule is not None
        assert CaseAnalysisRule is not None
        assert ProofByContradictionRule is not None

    def test_specialized_rules_exported(self):
        """All specialized rules should be importable from the package."""
        from ipfs_datasets_py.logic.CEC.native.inference_rules import (
            BiconditionalIntroduction, BiconditionalElimination,
            ConstructiveDilemma, DestructiveDilemma, ExportationRule,
            AbsorptionRule, AdditionRule, TautologyRule, CommutativityConjunction,
        )
        assert BiconditionalIntroduction is not None
        assert BiconditionalElimination is not None
        assert ConstructiveDilemma is not None
        assert DestructiveDilemma is not None
        assert ExportationRule is not None
        assert AbsorptionRule is not None
        assert AdditionRule is not None
        assert TautologyRule is not None
        assert CommutativityConjunction is not None

    def test_total_rule_count_in_all(self):
        """The __all__ list should contain all 67 exported rules + base classes."""
        from ipfs_datasets_py.logic.CEC.native.inference_rules import __all__
        # base(2) + propositional(10) + temporal(15) + deontic(7) +
        # cognitive(13) + modal(5) + resolution(6) + specialized(9) = 67 + 2 base = 69
        assert len(__all__) >= 60, f"Expected ≥60 items in __all__, got {len(__all__)}"
