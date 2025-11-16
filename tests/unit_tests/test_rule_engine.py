"""
Unit tests for Rule Engine

Tests the RuleEngine class for safe rule evaluation with JSON-Logic style predicates.
"""

import pytest
from unittest.mock import Mock

from ipfs_datasets_py.alerts.rule_engine import RuleEngine, RuleEvaluationError


class TestRuleEngineInitialization:
    """Test RuleEngine initialization."""
    
    def test_init_default(self):
        """
        GIVEN no parameters
        WHEN RuleEngine is initialized
        THEN expect default operators and predicates to be available
        """
        engine = RuleEngine()
        
        assert 'and' in engine.operators
        assert 'or' in engine.operators
        assert '>' in engine.operators
        assert 'var' in engine.operators
        assert 'zscore' in engine.custom_predicates
        assert 'sma' in engine.custom_predicates
    
    def test_init_with_custom_predicates(self):
        """
        GIVEN custom predicates dictionary
        WHEN RuleEngine is initialized
        THEN expect custom predicates to be registered
        """
        def custom_pred(value, context=None):
            return value * 2
        
        custom_predicates = {'double': custom_pred}
        engine = RuleEngine(custom_predicates=custom_predicates)
        
        assert 'double' in engine.custom_predicates
        assert 'double' in engine.operators


class TestRuleEngineLogicalOperators:
    """Test logical operators (and, or, not)."""
    
    def test_and_operator_true(self):
        """
        GIVEN a rule with AND operator and all true conditions
        WHEN evaluate is called
        THEN expect True
        """
        engine = RuleEngine()
        rule = {
            'and': [
                {'>': [5, 3]},
                {'<': [2, 4]}
            ]
        }
        
        result = engine.evaluate(rule, {})
        
        assert result is True
    
    def test_and_operator_false(self):
        """
        GIVEN a rule with AND operator and one false condition
        WHEN evaluate is called
        THEN expect False
        """
        engine = RuleEngine()
        rule = {
            'and': [
                {'>': [5, 3]},
                {'>': [2, 4]}
            ]
        }
        
        result = engine.evaluate(rule, {})
        
        assert result is False
    
    def test_or_operator_true(self):
        """
        GIVEN a rule with OR operator and at least one true condition
        WHEN evaluate is called
        THEN expect True
        """
        engine = RuleEngine()
        rule = {
            'or': [
                {'>': [5, 3]},
                {'>': [2, 4]}
            ]
        }
        
        result = engine.evaluate(rule, {})
        
        assert result is True
    
    def test_not_operator(self):
        """
        GIVEN a rule with NOT operator
        WHEN evaluate is called
        THEN expect negated result
        """
        engine = RuleEngine()
        rule = {'not': {'>': [3, 5]}}
        
        result = engine.evaluate(rule, {})
        
        assert result is True


class TestRuleEngineComparisonOperators:
    """Test comparison operators (>, <, >=, <=, ==, !=)."""
    
    def test_greater_than(self):
        """
        GIVEN a rule with > operator
        WHEN evaluate is called
        THEN expect correct comparison
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'>': [10, 5]}, {}) is True
        assert engine.evaluate({'>': [5, 10]}, {}) is False
        assert engine.evaluate({'>': [5, 5]}, {}) is False
    
    def test_less_than(self):
        """
        GIVEN a rule with < operator
        WHEN evaluate is called
        THEN expect correct comparison
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'<': [5, 10]}, {}) is True
        assert engine.evaluate({'<': [10, 5]}, {}) is False
        assert engine.evaluate({'<': [5, 5]}, {}) is False
    
    def test_greater_than_or_equal(self):
        """
        GIVEN a rule with >= operator
        WHEN evaluate is called
        THEN expect correct comparison
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'>=': [10, 5]}, {}) is True
        assert engine.evaluate({'>=': [5, 5]}, {}) is True
        assert engine.evaluate({'>=': [5, 10]}, {}) is False
    
    def test_less_than_or_equal(self):
        """
        GIVEN a rule with <= operator
        WHEN evaluate is called
        THEN expect correct comparison
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'<=': [5, 10]}, {}) is True
        assert engine.evaluate({'<=': [5, 5]}, {}) is True
        assert engine.evaluate({'<=': [10, 5]}, {}) is False
    
    def test_equal(self):
        """
        GIVEN a rule with == operator
        WHEN evaluate is called
        THEN expect correct equality check
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'==': [5, 5]}, {}) is True
        assert engine.evaluate({'==': [5, 10]}, {}) is False
        assert engine.evaluate({'==': ["test", "test"]}, {}) is True
    
    def test_not_equal(self):
        """
        GIVEN a rule with != operator
        WHEN evaluate is called
        THEN expect correct inequality check
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'!=': [5, 10]}, {}) is True
        assert engine.evaluate({'!=': [5, 5]}, {}) is False


class TestRuleEngineVariableAccess:
    """Test variable access from context."""
    
    def test_var_simple(self):
        """
        GIVEN a rule accessing a simple variable
        WHEN evaluate is called with context
        THEN expect variable value to be retrieved
        """
        engine = RuleEngine()
        rule = {'>': [{'var': 'price'}, 100]}
        context = {'price': 150}
        
        result = engine.evaluate(rule, context)
        
        assert result is True
    
    def test_var_nested(self):
        """
        GIVEN a rule accessing nested variable with dot notation
        WHEN evaluate is called with context
        THEN expect nested value to be retrieved
        """
        engine = RuleEngine()
        rule = {'==': [{'var': 'user.name'}, 'John']}
        context = {
            'user': {
                'name': 'John',
                'age': 30
            }
        }
        
        result = engine.evaluate(rule, context)
        
        assert result is True
    
    def test_var_not_found(self):
        """
        GIVEN a rule accessing non-existent variable
        WHEN evaluate is called
        THEN expect default value (None) to be used
        """
        engine = RuleEngine()
        rule = {'==': [{'var': 'missing'}, None]}
        context = {}
        
        result = engine.evaluate(rule, context)
        
        assert result is True


class TestRuleEngineMathOperators:
    """Test mathematical operators (+, -, *, /, abs, max, min)."""
    
    def test_addition(self):
        """
        GIVEN a rule with + operator
        WHEN evaluate is called
        THEN expect correct sum
        """
        engine = RuleEngine()
        rule = {'==': [{'+': [10, 20, 30]}, 60]}
        
        result = engine.evaluate(rule, {})
        
        assert result is True
    
    def test_subtraction(self):
        """
        GIVEN a rule with - operator
        WHEN evaluate is called
        THEN expect correct difference
        """
        engine = RuleEngine()
        rule = {'==': [{'-': [100, 30]}, 70]}
        
        result = engine.evaluate(rule, {})
        
        assert result is True
    
    def test_multiplication(self):
        """
        GIVEN a rule with * operator
        WHEN evaluate is called
        THEN expect correct product
        """
        engine = RuleEngine()
        rule = {'==': [{'*': [5, 10]}, 50]}
        
        result = engine.evaluate(rule, {})
        
        assert result is True
    
    def test_division(self):
        """
        GIVEN a rule with / operator
        WHEN evaluate is called
        THEN expect correct quotient
        """
        engine = RuleEngine()
        rule = {'==': [{'/': [100, 4]}, 25]}
        
        result = engine.evaluate(rule, {})
        
        assert result is True
    
    def test_division_by_zero(self):
        """
        GIVEN a rule with division by zero
        WHEN evaluate is called
        THEN expect RuleEvaluationError
        """
        engine = RuleEngine()
        rule = {'/': [100, 0]}
        
        with pytest.raises(RuleEvaluationError, match="Division by zero"):
            engine.evaluate(rule, {})
    
    def test_abs(self):
        """
        GIVEN a rule with abs operator
        WHEN evaluate is called
        THEN expect absolute value
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'==': [{'abs': -10}, 10]}, {}) is True
        assert engine.evaluate({'==': [{'abs': 10}, 10]}, {}) is True
    
    def test_max(self):
        """
        GIVEN a rule with max operator
        WHEN evaluate is called
        THEN expect maximum value
        """
        engine = RuleEngine()
        rule = {'==': [{'max': [5, 10, 3, 8]}, 10]}
        
        result = engine.evaluate(rule, {})
        
        assert result is True
    
    def test_min(self):
        """
        GIVEN a rule with min operator
        WHEN evaluate is called
        THEN expect minimum value
        """
        engine = RuleEngine()
        rule = {'==': [{'min': [5, 10, 3, 8]}, 3]}
        
        result = engine.evaluate(rule, {})
        
        assert result is True


class TestRuleEngineCollectionOperators:
    """Test collection operators (in, any, all)."""
    
    def test_in_operator_true(self):
        """
        GIVEN a rule checking if item is in collection
        WHEN evaluate is called with item in collection
        THEN expect True
        """
        engine = RuleEngine()
        rule = {'in': ['apple', ['apple', 'banana', 'orange']]}
        
        result = engine.evaluate(rule, {})
        
        assert result is True
    
    def test_in_operator_false(self):
        """
        GIVEN a rule checking if item is in collection
        WHEN evaluate is called with item not in collection
        THEN expect False
        """
        engine = RuleEngine()
        rule = {'in': ['grape', ['apple', 'banana', 'orange']]}
        
        result = engine.evaluate(rule, {})
        
        assert result is False
    
    def test_any_operator(self):
        """
        GIVEN a rule with any operator
        WHEN evaluate is called
        THEN expect True if any item is truthy
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'any': [False, True, False]}, {}) is True
        assert engine.evaluate({'any': [False, False, False]}, {}) is False
    
    def test_all_operator(self):
        """
        GIVEN a rule with all operator
        WHEN evaluate is called
        THEN expect True only if all items are truthy
        """
        engine = RuleEngine()
        
        assert engine.evaluate({'all': [True, True, True]}, {}) is True
        assert engine.evaluate({'all': [True, False, True]}, {}) is False


class TestRuleEngineStatisticalPredicates:
    """Test statistical predicates (zscore, sma, ema, stddev, percent_change)."""
    
    def test_sma_basic(self):
        """
        GIVEN a rule using sma predicate
        WHEN evaluate is called multiple times to build history
        THEN expect correct simple moving average
        """
        engine = RuleEngine()
        # Need to evaluate sma directly, not as root rule
        # Build history first
        context1 = {'price': 10}
        context2 = {'price': 20}
        context3 = {'price': 30}
        
        # Call the predicate to build history
        engine._pred_sma('price', 3, context=context1)
        engine._pred_sma('price', 3, context=context2)
        result = engine._pred_sma('price', 3, context=context3)
        
        # SMA(3) = (10 + 20 + 30) / 3 = 20
        assert result == 20.0
    
    def test_percent_change(self):
        """
        GIVEN a rule using percent_change predicate
        WHEN evaluate is called with price changes
        THEN expect correct percent change
        """
        engine = RuleEngine()
        
        # Build history
        context1 = {'price': 100}
        context2 = {'price': 110}
        
        engine._pred_percent_change('price', 1, context=context1)
        result = engine._pred_percent_change('price', 1, context=context2)
        
        # ((110 - 100) / 100) * 100 = 10%
        assert result == 10.0
    
    def test_zscore_basic(self):
        """
        GIVEN a rule using zscore predicate
        WHEN evaluate is called multiple times
        THEN expect z-score to be calculated
        """
        engine = RuleEngine()
        rule = {'zscore': ['value', 5]}
        
        # Build history with known values
        for val in [10, 10, 10, 10]:
            engine.evaluate(rule, {'value': val})
        
        # Current value significantly different
        result = engine.evaluate(rule, {'value': 20})
        
        # Z-score should be positive and > 0
        assert result > 0
    
    def test_reset_history(self):
        """
        GIVEN an engine with history
        WHEN reset_history is called
        THEN expect history to be cleared
        """
        engine = RuleEngine()
        
        # Build history
        engine.evaluate({'sma': ['price', 3]}, {'price': 10})
        engine.evaluate({'sma': ['price', 3]}, {'price': 20})
        
        assert 'price' in engine.history
        
        engine.reset_history('price')
        
        assert len(engine.history['price']) == 0


class TestRuleEngineCustomPredicates:
    """Test custom predicate registration."""
    
    def test_register_custom_predicate(self):
        """
        GIVEN a custom predicate function
        WHEN register_predicate is called
        THEN expect predicate to be available in rules
        """
        engine = RuleEngine()
        
        def custom_double(value, context=None):
            return value * 2
        
        engine.register_predicate('double', custom_double)
        
        assert 'double' in engine.operators
        
        rule = {'==': [{'double': 5}, 10]}
        result = engine.evaluate(rule, {})
        
        assert result is True


class TestRuleEngineErrorHandling:
    """Test error handling and edge cases."""
    
    def test_unknown_operator(self):
        """
        GIVEN a rule with unknown operator
        WHEN evaluate is called
        THEN expect RuleEvaluationError
        """
        engine = RuleEngine()
        rule = {'unknown_op': [1, 2]}
        
        with pytest.raises(RuleEvaluationError, match="Unknown operator"):
            engine.evaluate(rule, {})
    
    def test_invalid_rule_structure(self):
        """
        GIVEN a rule with multiple keys (invalid structure)
        WHEN evaluate is called
        THEN expect RuleEvaluationError
        """
        engine = RuleEngine()
        rule = {'>': [5, 3], '<': [2, 4]}  # Invalid: multiple keys
        
        with pytest.raises(RuleEvaluationError, match="exactly one key"):
            engine.evaluate(rule, {})
    
    def test_literal_values(self):
        """
        GIVEN literal values in rules
        WHEN evaluate is called
        THEN expect literals to be evaluated correctly
        """
        engine = RuleEngine()
        
        assert engine.evaluate(True, {}) is True
        assert engine.evaluate(False, {}) is False
        assert engine.evaluate(42, {}) is True  # Truthy
        assert engine.evaluate(0, {}) is False  # Falsy


class TestRuleEngineComplexRules:
    """Test complex multi-level rules."""
    
    def test_complex_nested_rule(self):
        """
        GIVEN a complex nested rule with multiple operators
        WHEN evaluate is called
        THEN expect correct evaluation
        """
        engine = RuleEngine()
        rule = {
            'and': [
                {'>': [{'var': 'price'}, 100]},
                {
                    'or': [
                        {'<': [{'var': 'volume'}, 1000]},
                        {'>': [{'var': 'volatility'}, 0.5]}
                    ]
                }
            ]
        }
        
        context = {
            'price': 150,
            'volume': 500,
            'volatility': 0.3
        }
        
        result = engine.evaluate(rule, context)
        
        assert result is True
    
    def test_rule_with_calculations(self):
        """
        GIVEN a rule combining math operations and comparisons
        WHEN evaluate is called
        THEN expect correct evaluation
        """
        engine = RuleEngine()
        rule = {
            '>': [
                {'+': [{'var': 'a'}, {'var': 'b'}]},
                {'*': [{'var': 'c'}, 2]}
            ]
        }
        
        context = {'a': 10, 'b': 20, 'c': 10}
        # (10 + 20) > (10 * 2) => 30 > 20 => True
        
        result = engine.evaluate(rule, context)
        
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
