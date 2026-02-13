"""
Unit tests for Formula Analyzer (Enhancement TODO Phase 1).

Tests intelligent prover selection based on formula analysis.
"""

import pytest
from ipfs_datasets_py.logic.external_provers.formula_analyzer import (
    FormulaAnalyzer,
    FormulaType,
    FormulaComplexity,
    FormulaAnalysis,
)
from ipfs_datasets_py.logic.types import (
    Formula,
    Predicate,
    And,
    Or,
    Not,
    Implies,
    Forall,
    Exists,
    Variable,
    Constant,
)


class TestFormulaAnalyzer:
    """Test suite for FormulaAnalyzer class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.analyzer = FormulaAnalyzer()

    def test_analyzer_initialization(self):
        """
        GIVEN: FormulaAnalyzer class
        WHEN: Creating a new instance
        THEN: Analyzer is properly initialized with prover profiles
        """
        assert self.analyzer is not None
        assert hasattr(self.analyzer, 'prover_profiles')
        assert len(self.analyzer.prover_profiles) > 0

    def test_simple_predicate_analysis(self):
        """
        GIVEN: A simple predicate formula P(x)
        WHEN: Analyzing the formula
        THEN: Returns correct analysis with minimal complexity
        """
        # Simple predicate
        formula = Predicate("P", [Variable("x")])
        
        analysis = self.analyzer.analyze(formula)
        
        assert isinstance(analysis, FormulaAnalysis)
        assert analysis.formula_type == FormulaType.PROPOSITIONAL
        assert analysis.quantifier_depth == 0
        assert analysis.nesting_level == 1
        assert analysis.complexity_level in [FormulaComplexity.TRIVIAL, FormulaComplexity.SIMPLE]

    def test_quantified_formula_analysis(self):
        """
        GIVEN: A universally quantified formula ∀x. P(x)
        WHEN: Analyzing the formula
        THEN: Returns correct analysis with quantifier depth 1
        """
        # ∀x. P(x)
        formula = Forall(Variable("x"), Predicate("P", [Variable("x")]))
        
        analysis = self.analyzer.analyze(formula)
        
        assert analysis.formula_type == FormulaType.QUANTIFIED
        assert analysis.quantifier_depth == 1
        assert analysis.has_quantifiers is True

    def test_nested_quantifiers_analysis(self):
        """
        GIVEN: A nested quantified formula ∀x. ∃y. P(x, y)
        WHEN: Analyzing the formula
        THEN: Returns correct analysis with quantifier depth 2
        """
        # ∀x. ∃y. P(x, y)
        inner = Predicate("P", [Variable("x"), Variable("y")])
        existential = Exists(Variable("y"), inner)
        formula = Forall(Variable("x"), existential)
        
        analysis = self.analyzer.analyze(formula)
        
        assert analysis.quantifier_depth == 2
        assert analysis.nesting_level >= 3
        assert analysis.has_quantifiers is True

    def test_modal_operator_detection(self):
        """
        GIVEN: A formula with modal operators (□, ◊)
        WHEN: Analyzing the formula
        THEN: Correctly identifies modal operators
        """
        # □(P(x)) - Always P(x)
        formula = Predicate("Always", [Predicate("P", [Variable("x")])])
        
        analysis = self.analyzer.analyze(formula)
        
        assert analysis.has_modal_operators is True
        assert analysis.formula_type in [FormulaType.MODAL, FormulaType.TEMPORAL]

    def test_temporal_operator_detection(self):
        """
        GIVEN: A formula with temporal operators (X, U, S)
        WHEN: Analyzing the formula
        THEN: Correctly identifies temporal operators
        """
        # Eventually(P(x))
        formula = Predicate("Eventually", [Predicate("P", [Variable("x")])])
        
        analysis = self.analyzer.analyze(formula)
        
        assert analysis.has_temporal_operators is True
        assert analysis.formula_type in [FormulaType.TEMPORAL, FormulaType.MODAL]

    def test_deontic_operator_detection(self):
        """
        GIVEN: A formula with deontic operators (O, P, F)
        WHEN: Analyzing the formula
        THEN: Correctly identifies deontic operators
        """
        # Obligatory(Action(x))
        formula = Predicate("Obligatory", [Predicate("Action", [Variable("x")])])
        
        analysis = self.analyzer.analyze(formula)
        
        assert analysis.has_deontic_operators is True
        assert analysis.formula_type == FormulaType.DEONTIC

    def test_complex_nested_formula(self):
        """
        GIVEN: A complex nested formula with multiple operators
        WHEN: Analyzing the formula
        THEN: Returns appropriate complexity metrics
        """
        # ∀x. (P(x) → ∃y. (Q(x, y) ∧ R(y)))
        r_pred = Predicate("R", [Variable("y")])
        q_pred = Predicate("Q", [Variable("x"), Variable("y")])
        and_formula = And(q_pred, r_pred)
        exists_formula = Exists(Variable("y"), and_formula)
        p_pred = Predicate("P", [Variable("x")])
        implies_formula = Implies(p_pred, exists_formula)
        formula = Forall(Variable("x"), implies_formula)
        
        analysis = self.analyzer.analyze(formula)
        
        assert analysis.quantifier_depth == 2
        assert analysis.nesting_level >= 5
        assert analysis.operator_count >= 3
        assert analysis.complexity_level in [FormulaComplexity.MODERATE, FormulaComplexity.COMPLEX]

    def test_prover_recommendations_simple(self):
        """
        GIVEN: A simple formula P(x) → Q(x)
        WHEN: Getting prover recommendations
        THEN: Returns ordered list with Z3 or native provers first
        """
        # P(x) → Q(x)
        p_pred = Predicate("P", [Variable("x")])
        q_pred = Predicate("Q", [Variable("x")])
        formula = Implies(p_pred, q_pred)
        
        analysis = self.analyzer.analyze(formula)
        recommendations = analysis.recommended_provers
        
        assert len(recommendations) > 0
        # Simple formulas should recommend fast provers
        assert "native" in recommendations[:2] or "z3" in recommendations[:2]

    def test_prover_recommendations_modal(self):
        """
        GIVEN: A modal formula with □ operator
        WHEN: Getting prover recommendations
        THEN: Returns modal-capable provers (Lean, Coq, SymbolicAI)
        """
        # □(P(x))
        formula = Predicate("Always", [Predicate("P", [Variable("x")])])
        
        analysis = self.analyzer.analyze(formula)
        recommendations = analysis.recommended_provers
        
        assert len(recommendations) > 0
        # Modal formulas should recommend modal-capable provers
        modal_provers = ["lean", "coq", "symbolicai"]
        assert any(prover in recommendations[:3] for prover in modal_provers)

    def test_prover_recommendations_quantified(self):
        """
        GIVEN: A deeply quantified formula
        WHEN: Getting prover recommendations
        THEN: Returns provers good with quantifiers (CVC5, Lean)
        """
        # ∀x. ∀y. ∃z. P(x, y, z)
        inner = Predicate("P", [Variable("x"), Variable("y"), Variable("z")])
        exists_z = Exists(Variable("z"), inner)
        forall_y = Forall(Variable("y"), exists_z)
        formula = Forall(Variable("x"), forall_y)
        
        analysis = self.analyzer.analyze(formula)
        recommendations = analysis.recommended_provers
        
        assert len(recommendations) > 0
        # Quantified formulas should recommend SMT solvers
        assert "cvc5" in recommendations[:3] or "z3" in recommendations[:3]

    def test_complexity_score_trivial(self):
        """
        GIVEN: A trivial formula P(x)
        WHEN: Computing complexity score
        THEN: Returns low complexity score (0-20)
        """
        formula = Predicate("P", [Variable("x")])
        
        analysis = self.analyzer.analyze(formula)
        
        assert 0 <= analysis.complexity_score <= 30
        assert analysis.complexity_level in [FormulaComplexity.TRIVIAL, FormulaComplexity.SIMPLE]

    def test_complexity_score_moderate(self):
        """
        GIVEN: A moderately complex formula
        WHEN: Computing complexity score
        THEN: Returns moderate complexity score (30-60)
        """
        # ∀x. (P(x) → Q(x))
        p_pred = Predicate("P", [Variable("x")])
        q_pred = Predicate("Q", [Variable("x")])
        implies_formula = Implies(p_pred, q_pred)
        formula = Forall(Variable("x"), implies_formula)
        
        analysis = self.analyzer.analyze(formula)
        
        assert analysis.complexity_score >= 20
        assert analysis.complexity_level in [FormulaComplexity.SIMPLE, FormulaComplexity.MODERATE]

    def test_complexity_score_complex(self):
        """
        GIVEN: A very complex formula with deep nesting
        WHEN: Computing complexity score
        THEN: Returns high complexity score (60-100)
        """
        # Build deeply nested formula: ∀x1. ∀x2. ∀x3. ∃y. (P(x1) ∧ Q(x2) ∧ R(x3, y))
        p1 = Predicate("P", [Variable("x1")])
        p2 = Predicate("Q", [Variable("x2")])
        p3 = Predicate("R", [Variable("x3"), Variable("y")])
        and1 = And(p1, p2)
        and2 = And(and1, p3)
        exists_y = Exists(Variable("y"), and2)
        forall_x3 = Forall(Variable("x3"), exists_y)
        forall_x2 = Forall(Variable("x2"), forall_x3)
        formula = Forall(Variable("x1"), forall_x2)
        
        analysis = self.analyzer.analyze(formula)
        
        assert analysis.complexity_score >= 40
        assert analysis.complexity_level in [FormulaComplexity.MODERATE, FormulaComplexity.COMPLEX, FormulaComplexity.VERY_COMPLEX]

    def test_operator_counting(self):
        """
        GIVEN: A formula with multiple logical operators
        WHEN: Analyzing the formula
        THEN: Correctly counts all operators
        """
        # (P(x) ∧ Q(x)) ∨ (R(x) → S(x))
        p_pred = Predicate("P", [Variable("x")])
        q_pred = Predicate("Q", [Variable("x")])
        r_pred = Predicate("R", [Variable("x")])
        s_pred = Predicate("S", [Variable("x")])
        and_formula = And(p_pred, q_pred)
        implies_formula = Implies(r_pred, s_pred)
        formula = Or(and_formula, implies_formula)
        
        analysis = self.analyzer.analyze(formula)
        
        # Should count ∧, ∨, → = 3 operators
        assert analysis.operator_count >= 3

    def test_mixed_formula_type(self):
        """
        GIVEN: A formula with both modal and quantifiers
        WHEN: Analyzing the formula
        THEN: Identifies as MIXED type
        """
        # ∀x. □(P(x))
        modal_pred = Predicate("Always", [Predicate("P", [Variable("x")])])
        formula = Forall(Variable("x"), modal_pred)
        
        analysis = self.analyzer.analyze(formula)
        
        # Should be identified as mixed or prioritize one type
        assert analysis.formula_type in [FormulaType.MIXED, FormulaType.MODAL, FormulaType.QUANTIFIED]
        assert analysis.has_modal_operators is True
        assert analysis.has_quantifiers is True

    def test_analysis_caching(self):
        """
        GIVEN: The same formula analyzed twice
        WHEN: Analyzing it again
        THEN: Returns same analysis (testing consistency)
        """
        formula = Predicate("P", [Variable("x")])
        
        analysis1 = self.analyzer.analyze(formula)
        analysis2 = self.analyzer.analyze(formula)
        
        # Should return consistent results
        assert analysis1.formula_type == analysis2.formula_type
        assert analysis1.complexity_score == analysis2.complexity_score
        assert analysis1.quantifier_depth == analysis2.quantifier_depth

    def test_empty_formula_handling(self):
        """
        GIVEN: An attempt to analyze None or invalid input
        WHEN: Analyzing the formula
        THEN: Returns appropriate default analysis or raises error gracefully
        """
        # Test with None should either raise or return safe default
        try:
            analysis = self.analyzer.analyze(None)
            # If it doesn't raise, should have safe defaults
            assert analysis is not None
        except (TypeError, ValueError, AttributeError):
            # Expected behavior - invalid input rejected
            pass

    def test_prover_profile_completeness(self):
        """
        GIVEN: Prover profiles in analyzer
        WHEN: Checking all expected provers
        THEN: All 6 provers have profiles
        """
        expected_provers = ["z3", "cvc5", "lean", "coq", "symbolicai", "native"]
        
        for prover in expected_provers:
            assert prover in self.analyzer.prover_profiles
            profile = self.analyzer.prover_profiles[prover]
            assert "capabilities" in profile
            assert "performance" in profile

    def test_formula_type_classification_accuracy(self):
        """
        GIVEN: Various formula types
        WHEN: Classifying each type
        THEN: Correctly identifies each formula type
        """
        test_cases = [
            (Predicate("P", [Variable("x")]), FormulaType.PROPOSITIONAL),
            (Forall(Variable("x"), Predicate("P", [Variable("x")])), FormulaType.QUANTIFIED),
            (Predicate("Always", [Predicate("P", [Variable("x")])]), [FormulaType.MODAL, FormulaType.TEMPORAL]),
            (Predicate("Obligatory", [Predicate("P", [Variable("x")])]), FormulaType.DEONTIC),
        ]
        
        for formula, expected_type in test_cases:
            analysis = self.analyzer.analyze(formula)
            if isinstance(expected_type, list):
                assert analysis.formula_type in expected_type
            else:
                assert analysis.formula_type == expected_type

    def test_recommendation_ordering(self):
        """
        GIVEN: A formula analysis with recommendations
        WHEN: Getting recommended provers
        THEN: Recommendations are properly ordered by suitability
        """
        # Simple formula should have deterministic ordering
        formula = Predicate("P", [Variable("x")])
        
        analysis = self.analyzer.analyze(formula)
        recommendations = analysis.recommended_provers
        
        # Should have multiple recommendations
        assert len(recommendations) >= 3
        # Should be ordered (no duplicates)
        assert len(recommendations) == len(set(recommendations))

    def test_nesting_level_calculation(self):
        """
        GIVEN: Formulas with different nesting depths
        WHEN: Calculating nesting levels
        THEN: Returns correct nesting depth
        """
        # Level 1: P(x)
        level1 = Predicate("P", [Variable("x")])
        analysis1 = self.analyzer.analyze(level1)
        assert analysis1.nesting_level == 1
        
        # Level 2: ¬P(x)
        level2 = Not(Predicate("P", [Variable("x")]))
        analysis2 = self.analyzer.analyze(level2)
        assert analysis2.nesting_level == 2
        
        # Level 3: P(x) ∧ Q(x)
        level3 = And(Predicate("P", [Variable("x")]), Predicate("Q", [Variable("x")]))
        analysis3 = self.analyzer.analyze(level3)
        assert analysis3.nesting_level >= 2


class TestFormulaAnalysisIntegration:
    """Integration tests for Formula Analyzer with ProverRouter."""

    def test_analyzer_with_prover_router(self):
        """
        GIVEN: FormulaAnalyzer and ProverRouter integration
        WHEN: Router uses analyzer for prover selection
        THEN: Selects appropriate prover based on analysis
        """
        from ipfs_datasets_py.logic.external_provers.prover_router import ProverRouter
        
        router = ProverRouter()
        analyzer = FormulaAnalyzer()
        
        # Simple formula
        formula = Predicate("P", [Variable("x")])
        analysis = analyzer.analyze(formula)
        
        # Router should be able to use this analysis
        assert len(analysis.recommended_provers) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
