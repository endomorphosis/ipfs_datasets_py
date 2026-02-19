"""
Integration tests for TDFOL system.

Tests end-to-end workflows combining multiple components.
"""

import pytest
from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    Predicate, BinaryFormula, LogicOperator, create_implication,
    create_conjunction, create_obligation, create_always
)
from ipfs_datasets_py.logic.TDFOL.inference_rules.propositional import ModusPonensRule
from ipfs_datasets_py.logic.TDFOL.inference_rules.deontic import DeonticDAxiomRule


class TestInferenceRuleChaining:
    """Test chaining multiple inference rules together"""
    
    def test_modus_ponens_chain(self):
        """Test chaining multiple modus ponens applications"""
        # GIVEN P, P→Q, Q→R
        p = Predicate('P', [])
        q = Predicate('Q', [])
        r = Predicate('R', [])
        p_implies_q = create_implication(p, q)
        q_implies_r = create_implication(q, r)
        rule = ModusPonensRule()
        
        # WHEN applying modus ponens twice
        result1 = rule.apply(p, p_implies_q)  # Get Q
        result2 = rule.apply(result1, q_implies_r)  # Get R from Q
        
        # THEN we should derive R
        assert result2 == r
    
    def test_propositional_to_deontic_chain(self):
        """Test combining propositional and deontic rules"""
        # GIVEN O(P) and deontic D axiom
        p = Predicate('P', [])
        o_p = create_obligation(p)
        d_axiom = DeonticDAxiomRule()
        
        # WHEN applying D axiom
        result = d_axiom.apply(o_p)
        
        # THEN we get P(P)
        assert result is not None
        assert hasattr(result, 'operator')


class TestFormulaConstruction:
    """Test complex formula construction"""
    
    def test_nested_obligation_construction(self):
        """Test constructing nested obligations"""
        # GIVEN predicates
        p = Predicate('Pay', [])
        
        # WHEN creating O(□P)
        always_p = create_always(p)
        o_always_p = create_obligation(always_p)
        
        # THEN formula should be well-formed
        assert o_always_p is not None
        assert hasattr(o_always_p, 'formula')
    
    def test_complex_conditional_construction(self):
        """Test building complex conditionals"""
        # GIVEN predicates
        p = Predicate('Contractor', [])
        q = Predicate('PayTaxes', [])
        r = Predicate('ReportIncome', [])
        
        # WHEN creating (P ∧ Q) → R
        p_and_q = create_conjunction(p, q)
        conditional = create_implication(p_and_q, r)
        
        # THEN formula should be valid
        assert conditional is not None
        assert isinstance(conditional, BinaryFormula)
        assert conditional.operator == LogicOperator.IMPLIES


class TestRuleApplicationValidation:
    """Test validation of rule applications"""
    
    def test_modus_ponens_invalid_inputs(self):
        """Test modus ponens rejects invalid inputs"""
        # GIVEN wrong number of formulas
        p = Predicate('P', [])
        rule = ModusPonensRule()
        
        # WHEN checking with only one formula
        can_apply = rule.can_apply(p)
        
        # THEN it should reject
        assert can_apply is False
    
    def test_rule_type_checking(self):
        """Test rules check formula types correctly"""
        # GIVEN a deontic rule and non-deontic formula
        p = Predicate('P', [])
        rule = DeonticDAxiomRule()
        
        # WHEN checking if rule can apply
        can_apply = rule.can_apply(p)
        
        # THEN it should reject
        assert can_apply is False


class TestFormulaEquality:
    """Test formula equality comparisons"""
    
    def test_predicate_equality(self):
        """Test that identical predicates are equal"""
        # GIVEN two identical predicates
        p1 = Predicate('P', [])
        p2 = Predicate('P', [])
        
        # WHEN comparing
        are_equal = (p1 == p2)
        
        # THEN they should be equal
        assert are_equal is True
    
    def test_formula_inequality(self):
        """Test that different formulas are not equal"""
        # GIVEN two different predicates
        p = Predicate('P', [])
        q = Predicate('Q', [])
        
        # WHEN comparing
        are_equal = (p == q)
        
        # THEN they should not be equal
        assert are_equal is False
    
    def test_complex_formula_equality(self):
        """Test equality of complex formulas"""
        # GIVEN two identical implications
        p = Predicate('P', [])
        q = Predicate('Q', [])
        impl1 = create_implication(p, q)
        impl2 = create_implication(p, q)
        
        # WHEN comparing
        are_equal = (impl1 == impl2)
        
        # THEN they should be equal
        assert are_equal is True


class TestErrorHandling:
    """Test error handling across modules"""
    
    def test_rule_application_with_none(self):
        """Test that rules handle None inputs gracefully"""
        # GIVEN None input
        rule = ModusPonensRule()
        
        # WHEN checking if rule can apply to None
        # THEN it should not crash (may return False or raise TypeError)
        try:
            result = rule.can_apply(None)
            assert result is False
        except (TypeError, AttributeError):
            # Acceptable to raise exception for None
            pass
    
    def test_invalid_formula_construction(self):
        """Test handling of invalid formula construction"""
        # GIVEN invalid inputs
        # WHEN attempting to create implication with non-formulas
        # THEN it should handle gracefully
        try:
            # This may raise TypeError or create invalid formula
            result = create_implication(None, None)
            # If it doesn't raise, result should be None or invalid
            assert result is None or hasattr(result, 'left')
        except (TypeError, AttributeError):
            # Acceptable to raise exception
            pass


class TestPerformance:
    """Basic performance tests"""
    
    def test_formula_creation_speed(self):
        """Test that formula creation is reasonably fast"""
        import time
        
        # GIVEN predicates
        p = Predicate('P', [])
        q = Predicate('Q', [])
        
        # WHEN creating many implications
        start = time.time()
        for _ in range(1000):
            create_implication(p, q)
        elapsed = time.time() - start
        
        # THEN it should complete quickly (< 1 second for 1000)
        assert elapsed < 1.0
    
    def test_rule_application_speed(self):
        """Test that rule application is reasonably fast"""
        import time
        
        # GIVEN rule and formulas
        p = Predicate('P', [])
        q = Predicate('Q', [])
        p_implies_q = create_implication(p, q)
        rule = ModusPonensRule()
        
        # WHEN checking can_apply many times
        start = time.time()
        for _ in range(1000):
            rule.can_apply(p, p_implies_q)
        elapsed = time.time() - start
        
        # THEN it should complete quickly (< 0.5 seconds for 1000)
        assert elapsed < 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
