"""
Tests for Temporal Operators (Phase 4 Week 1)

This test module validates temporal reasoning capabilities in DCEC,
including all temporal operators and their evaluation over time sequences.

Test Coverage:
- Temporal operator construction and validation (3 tests)
- Always (□) operator evaluation (2 tests)
- Eventually (◇) operator evaluation (2 tests)
- Next (X) operator evaluation (2 tests)
- Until (U) operator evaluation (2 tests)
- Since (S) operator evaluation (2 tests)
- Yesterday (Y) operator evaluation (2 tests)

Total: 15 tests
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.temporal import (
    TemporalOperator,
    TemporalFormula,
    State,
    always,
    eventually,
    next_op,
    until,
    since,
    yesterday,
)
from ipfs_datasets_py.logic.CEC.native.dcec_namespace import DCECNamespace
from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    AtomicFormula,
    Predicate,
)
from ipfs_datasets_py.logic.CEC.native.exceptions import ValidationError


class TestTemporalOperatorConstruction:
    """Test temporal operator construction and validation."""
    
    def test_unary_operator_construction(self):
        """
        GIVEN a base formula
        WHEN creating a unary temporal operator (ALWAYS, EVENTUALLY, NEXT, YESTERDAY)
        THEN the operator should be constructed successfully
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        # WHEN
        always_p = TemporalFormula(TemporalOperator.ALWAYS, formula)
        eventually_p = TemporalFormula(TemporalOperator.EVENTUALLY, formula)
        next_p = TemporalFormula(TemporalOperator.NEXT, formula)
        yesterday_p = TemporalFormula(TemporalOperator.YESTERDAY, formula)
        
        # THEN
        assert always_p.operator == TemporalOperator.ALWAYS
        assert always_p.formula == formula
        assert always_p.formula2 is None
        
        assert eventually_p.operator == TemporalOperator.EVENTUALLY
        assert next_p.operator == TemporalOperator.NEXT
        assert yesterday_p.operator == TemporalOperator.YESTERDAY
    
    def test_binary_operator_construction(self):
        """
        GIVEN two base formulas
        WHEN creating a binary temporal operator (UNTIL, SINCE)
        THEN the operator should be constructed successfully
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        q = namespace.add_predicate("Q", [])
        formula1 = AtomicFormula(p, [])
        formula2 = AtomicFormula(q, [])
        
        # WHEN
        p_until_q = TemporalFormula(TemporalOperator.UNTIL, formula1, formula2)
        p_since_q = TemporalFormula(TemporalOperator.SINCE, formula1, formula2)
        
        # THEN
        assert p_until_q.operator == TemporalOperator.UNTIL
        assert p_until_q.formula == formula1
        assert p_until_q.formula2 == formula2
        
        assert p_since_q.operator == TemporalOperator.SINCE
        assert p_since_q.formula == formula1
        assert p_since_q.formula2 == formula2
    
    def test_invalid_operator_formula_combination(self):
        """
        GIVEN a base formula
        WHEN creating a binary operator with only one formula
        THEN ValidationError should be raised
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        # WHEN/THEN
        with pytest.raises(ValidationError, match="requires two formulas"):
            TemporalFormula(TemporalOperator.UNTIL, formula)
        
        with pytest.raises(ValidationError, match="requires two formulas"):
            TemporalFormula(TemporalOperator.SINCE, formula)


class TestAlwaysOperator:
    """Test ALWAYS (□) temporal operator."""
    
    def test_always_true_sequence(self):
        """
        GIVEN a sequence where p is always true
        WHEN evaluating □p
        THEN result should be True
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        states = [
            State(0, {'P': True}),
            State(1, {'P': True}),
            State(2, {'P': True}),
        ]
        
        # WHEN
        always_p = always(formula)
        result = always_p.evaluate(states, current_time=0)
        
        # THEN
        assert result is True
    
    def test_always_false_with_violation(self):
        """
        GIVEN a sequence where p becomes false
        WHEN evaluating □p
        THEN result should be False
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        states = [
            State(0, {'P': True}),
            State(1, {'P': False}),  # Violation
            State(2, {'P': True}),
        ]
        
        # WHEN
        always_p = always(formula)
        result = always_p.evaluate(states, current_time=0)
        
        # THEN
        assert result is False


class TestEventuallyOperator:
    """Test EVENTUALLY (◇) temporal operator."""
    
    def test_eventually_true_at_end(self):
        """
        GIVEN a sequence where p becomes true eventually
        WHEN evaluating ◇p
        THEN result should be True
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        states = [
            State(0, {'P': False}),
            State(1, {'P': False}),
            State(2, {'P': True}),  # Eventually true
        ]
        
        # WHEN
        eventually_p = eventually(formula)
        result = eventually_p.evaluate(states, current_time=0)
        
        # THEN
        assert result is True
    
    def test_eventually_never_true(self):
        """
        GIVEN a sequence where p is never true
        WHEN evaluating ◇p
        THEN result should be False
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        states = [
            State(0, {'P': False}),
            State(1, {'P': False}),
            State(2, {'P': False}),
        ]
        
        # WHEN
        eventually_p = eventually(formula)
        result = eventually_p.evaluate(states, current_time=0)
        
        # THEN
        assert result is False


class TestNextOperator:
    """Test NEXT (X) temporal operator."""
    
    def test_next_true_in_next_state(self):
        """
        GIVEN a sequence where p is true in next state
        WHEN evaluating X p at current state
        THEN result should be True
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        states = [
            State(0, {'P': False}),
            State(1, {'P': True}),   # Next state
            State(2, {'P': False}),
        ]
        
        # WHEN
        next_p = next_op(formula)
        result = next_p.evaluate(states, current_time=0)
        
        # THEN
        assert result is True
    
    def test_next_no_next_state(self):
        """
        GIVEN a sequence with no next state (at end)
        WHEN evaluating X p
        THEN result should be False (by convention)
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        states = [
            State(0, {'P': False}),
            State(1, {'P': True}),
        ]
        
        # WHEN
        next_p = next_op(formula)
        result = next_p.evaluate(states, current_time=1)  # At end
        
        # THEN
        assert result is False


class TestUntilOperator:
    """Test UNTIL (U) temporal operator."""
    
    def test_until_condition_satisfied(self):
        """
        GIVEN a sequence where p holds until q becomes true
        WHEN evaluating p U q
        THEN result should be True
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        q = namespace.add_predicate("Q", [])
        formula_p = AtomicFormula(p, [])
        formula_q = AtomicFormula(q, [])
        
        states = [
            State(0, {'P': True, 'Q': False}),
            State(1, {'P': True, 'Q': False}),
            State(2, {'P': True, 'Q': True}),  # Q becomes true
        ]
        
        # WHEN
        p_until_q = until(formula_p, formula_q)
        result = p_until_q.evaluate(states, current_time=0)
        
        # THEN
        assert result is True
    
    def test_until_first_formula_violated(self):
        """
        GIVEN a sequence where p becomes false before q is true
        WHEN evaluating p U q
        THEN result should be False
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        q = namespace.add_predicate("Q", [])
        formula_p = AtomicFormula(p, [])
        formula_q = AtomicFormula(q, [])
        
        states = [
            State(0, {'P': True, 'Q': False}),
            State(1, {'P': False, 'Q': False}),  # P violated
            State(2, {'P': True, 'Q': True}),
        ]
        
        # WHEN
        p_until_q = until(formula_p, formula_q)
        result = p_until_q.evaluate(states, current_time=0)
        
        # THEN
        assert result is False


class TestSinceOperator:
    """Test SINCE (S) temporal operator."""
    
    def test_since_condition_satisfied(self):
        """
        GIVEN a sequence where p has held since q was true
        WHEN evaluating p S q at current time
        THEN result should be True
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        q = namespace.add_predicate("Q", [])
        formula_p = AtomicFormula(p, [])
        formula_q = AtomicFormula(q, [])
        
        states = [
            State(0, {'P': False, 'Q': True}),  # Q was true
            State(1, {'P': True, 'Q': False}),  # P since then
            State(2, {'P': True, 'Q': False}),  # Current
        ]
        
        # WHEN
        p_since_q = since(formula_p, formula_q)
        result = p_since_q.evaluate(states, current_time=2)
        
        # THEN
        assert result is True
    
    def test_since_never_true(self):
        """
        GIVEN a sequence where q was never true
        WHEN evaluating p S q
        THEN result should be False
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        q = namespace.add_predicate("Q", [])
        formula_p = AtomicFormula(p, [])
        formula_q = AtomicFormula(q, [])
        
        states = [
            State(0, {'P': True, 'Q': False}),
            State(1, {'P': True, 'Q': False}),
            State(2, {'P': True, 'Q': False}),
        ]
        
        # WHEN
        p_since_q = since(formula_p, formula_q)
        result = p_since_q.evaluate(states, current_time=2)
        
        # THEN
        assert result is False


class TestYesterdayOperator:
    """Test YESTERDAY (Y) temporal operator."""
    
    def test_yesterday_true_in_previous_state(self):
        """
        GIVEN a sequence where p was true in previous state
        WHEN evaluating Y p
        THEN result should be True
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        states = [
            State(0, {'P': True}),   # Previous state
            State(1, {'P': False}),  # Current state
        ]
        
        # WHEN
        yesterday_p = yesterday(formula)
        result = yesterday_p.evaluate(states, current_time=1)
        
        # THEN
        assert result is True
    
    def test_yesterday_no_previous_state(self):
        """
        GIVEN a sequence at the first state
        WHEN evaluating Y p
        THEN result should be False (by convention)
        """
        # GIVEN
        namespace = DCECNamespace()
        p = namespace.add_predicate("P", [])
        formula = AtomicFormula(p, [])
        
        states = [
            State(0, {'P': True}),
        ]
        
        # WHEN
        yesterday_p = yesterday(formula)
        result = yesterday_p.evaluate(states, current_time=0)
        
        # THEN
        assert result is False
