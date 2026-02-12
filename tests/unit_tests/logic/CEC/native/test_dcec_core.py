"""
Unit tests for native DCEC core implementation.

These tests validate the core DCEC logic components.
"""

import pytest
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    DeonticOperator,
    CognitiveOperator,
    LogicalConnective,
    TemporalOperator,
    Sort,
    Variable,
    Function,
    Predicate,
    VariableTerm,
    FunctionTerm,
    AtomicFormula,
    DeonticFormula,
    CognitiveFormula,
    TemporalFormula,
    ConnectiveFormula,
    QuantifiedFormula,
    DCECStatement,
)


class TestDeonticOperator:
    """Test suite for DeonticOperator enum."""
    
    def test_deontic_operators_exist(self):
        """
        GIVEN DeonticOperator enum
        WHEN accessing operator values
        THEN all expected operators should be present
        """
        assert DeonticOperator.OBLIGATION.value == "O"
        assert DeonticOperator.PERMISSION.value == "P"
        assert DeonticOperator.PROHIBITION.value == "F"
        assert DeonticOperator.RIGHT.value == "R"


class TestCognitiveOperator:
    """Test suite for CognitiveOperator enum."""
    
    def test_cognitive_operators_exist(self):
        """
        GIVEN CognitiveOperator enum
        WHEN accessing operator values
        THEN all expected operators should be present
        """
        assert CognitiveOperator.BELIEF.value == "B"
        assert CognitiveOperator.KNOWLEDGE.value == "K"
        assert CognitiveOperator.INTENTION.value == "I"


class TestSort:
    """Test suite for Sort class."""
    
    def test_sort_creation(self):
        """
        GIVEN a sort name
        WHEN creating a Sort
        THEN it should have correct attributes
        """
        sort = Sort("Entity")
        assert sort.name == "Entity"
        assert sort.parent is None
    
    def test_sort_with_parent(self):
        """
        GIVEN a sort with a parent
        WHEN creating a Sort hierarchy
        THEN subtype relationship should work
        """
        entity = Sort("Entity")
        agent = Sort("Agent", entity)
        
        assert agent.parent == entity
        assert agent.is_subtype_of(entity)
        assert agent.is_subtype_of(agent)
        assert not entity.is_subtype_of(agent)


class TestVariable:
    """Test suite for Variable class."""
    
    def test_variable_creation(self):
        """
        GIVEN a variable name and sort
        WHEN creating a Variable
        THEN it should have correct attributes
        """
        agent_sort = Sort("Agent")
        var = Variable("x", agent_sort)
        
        assert var.name == "x"
        assert var.sort == agent_sort
        assert "x" in str(var)
        assert "Agent" in str(var)


class TestFunction:
    """Test suite for Function class."""
    
    def test_function_creation(self):
        """
        GIVEN function signature
        WHEN creating a Function
        THEN it should have correct attributes
        """
        agent = Sort("Agent")
        action = Sort("Action")
        
        func = Function("perform", [agent], action)
        
        assert func.name == "perform"
        assert func.arity() == 1
        assert func.return_sort == action


class TestPredicate:
    """Test suite for Predicate class."""
    
    def test_predicate_creation(self):
        """
        GIVEN predicate signature
        WHEN creating a Predicate
        THEN it should have correct attributes
        """
        agent = Sort("Agent")
        pred = Predicate("isHonest", [agent])
        
        assert pred.name == "isHonest"
        assert pred.arity() == 1


class TestVariableTerm:
    """Test suite for VariableTerm class."""
    
    def test_variable_term_creation(self):
        """
        GIVEN a variable
        WHEN creating a VariableTerm
        THEN it should wrap the variable correctly
        """
        agent_sort = Sort("Agent")
        var = Variable("x", agent_sort)
        term = VariableTerm(var)
        
        assert term.get_sort() == agent_sort
        assert var in term.get_free_variables()
    
    def test_variable_term_substitution(self):
        """
        GIVEN a variable term and substitution
        WHEN substituting
        THEN it should replace the variable
        """
        agent_sort = Sort("Agent")
        x = Variable("x", agent_sort)
        y = Variable("y", agent_sort)
        
        term_x = VariableTerm(x)
        term_y = VariableTerm(y)
        
        result = term_x.substitute(x, term_y)
        assert isinstance(result, VariableTerm)
        assert result.variable == y


class TestFunctionTerm:
    """Test suite for FunctionTerm class."""
    
    def test_function_term_creation(self):
        """
        GIVEN a function and arguments
        WHEN creating a FunctionTerm
        THEN it should validate arity
        """
        agent = Sort("Agent")
        action = Sort("Action")
        func = Function("perform", [agent], action)
        
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        func_term = FunctionTerm(func, [term_x])
        
        assert func_term.get_sort() == action
        assert x in func_term.get_free_variables()
    
    def test_function_term_arity_validation(self):
        """
        GIVEN a function with specific arity
        WHEN creating FunctionTerm with wrong arity
        THEN it should raise ValueError
        """
        agent = Sort("Agent")
        action = Sort("Action")
        func = Function("perform", [agent, agent], action)
        
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        with pytest.raises(ValueError):
            FunctionTerm(func, [term_x])  # Should need 2 arguments


class TestAtomicFormula:
    """Test suite for AtomicFormula class."""
    
    def test_atomic_formula_creation(self):
        """
        GIVEN a predicate and arguments
        WHEN creating an AtomicFormula
        THEN it should create valid formula
        """
        agent = Sort("Agent")
        pred = Predicate("isHonest", [agent])
        
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        formula = AtomicFormula(pred, [term_x])
        
        assert x in formula.get_free_variables()
        assert "isHonest" in formula.to_string()


class TestDeonticFormula:
    """Test suite for DeonticFormula class."""
    
    def test_deontic_formula_creation(self):
        """
        GIVEN a formula and deontic operator
        WHEN creating a DeonticFormula
        THEN it should wrap the formula correctly
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        base_formula = AtomicFormula(pred, [term_x])
        deontic_formula = DeonticFormula(DeonticOperator.OBLIGATION, base_formula)
        
        assert "O" in deontic_formula.to_string()
        assert "act" in deontic_formula.to_string()


class TestCognitiveFormula:
    """Test suite for CognitiveFormula class."""
    
    def test_cognitive_formula_creation(self):
        """
        GIVEN a formula, agent, and cognitive operator
        WHEN creating a CognitiveFormula
        THEN it should represent mental states correctly
        """
        agent = Sort("Agent")
        pred = Predicate("goal", [])
        
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        base_formula = AtomicFormula(pred, [])
        cognitive_formula = CognitiveFormula(
            CognitiveOperator.BELIEF,
            term_x,
            base_formula
        )
        
        assert "B" in cognitive_formula.to_string()
        assert x in cognitive_formula.get_free_variables()


class TestTemporalFormula:
    """Test suite for TemporalFormula class."""
    
    def test_temporal_formula_creation(self):
        """
        GIVEN a formula and temporal operator
        WHEN creating a TemporalFormula
        THEN it should represent temporal logic correctly
        """
        agent = Sort("Agent")
        pred = Predicate("complete", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        base_formula = AtomicFormula(pred, [term_x])
        temporal_formula = TemporalFormula(
            TemporalOperator.EVENTUALLY,
            base_formula
        )
        
        assert "◊" in temporal_formula.to_string()


class TestConnectiveFormula:
    """Test suite for ConnectiveFormula class."""
    
    def test_and_connective(self):
        """
        GIVEN two formulas
        WHEN creating AND connective
        THEN it should combine them correctly
        """
        agent = Sort("Agent")
        pred1 = Predicate("p1", [])
        pred2 = Predicate("p2", [])
        
        formula1 = AtomicFormula(pred1, [])
        formula2 = AtomicFormula(pred2, [])
        
        and_formula = ConnectiveFormula(LogicalConnective.AND, [formula1, formula2])
        
        assert "∧" in and_formula.to_string()
    
    def test_not_connective_arity(self):
        """
        GIVEN NOT connective
        WHEN creating with wrong arity
        THEN it should validate
        """
        pred = Predicate("p", [])
        formula = AtomicFormula(pred, [])
        
        # Should work with 1 formula
        not_formula = ConnectiveFormula(LogicalConnective.NOT, [formula])
        assert "¬" in not_formula.to_string()
        
        # Should fail with 2 formulas
        with pytest.raises(ValueError):
            ConnectiveFormula(LogicalConnective.NOT, [formula, formula])


class TestQuantifiedFormula:
    """Test suite for QuantifiedFormula class."""
    
    def test_forall_quantifier(self):
        """
        GIVEN a formula with free variables
        WHEN creating universal quantification
        THEN bound variable should not be free
        """
        agent = Sort("Agent")
        pred = Predicate("isHonest", [agent])
        
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        base_formula = AtomicFormula(pred, [term_x])
        quantified = QuantifiedFormula(LogicalConnective.FORALL, x, base_formula)
        
        assert x not in quantified.get_free_variables()
        assert "∀" in quantified.to_string()
    
    def test_exists_quantifier(self):
        """
        GIVEN a formula with free variables
        WHEN creating existential quantification
        THEN bound variable should not be free
        """
        agent = Sort("Agent")
        pred = Predicate("exists", [agent])
        
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        base_formula = AtomicFormula(pred, [term_x])
        quantified = QuantifiedFormula(LogicalConnective.EXISTS, x, base_formula)
        
        assert x not in quantified.get_free_variables()
        assert "∃" in quantified.to_string()


class TestDCECStatement:
    """Test suite for DCECStatement class."""
    
    def test_statement_creation(self):
        """
        GIVEN a formula
        WHEN creating a DCECStatement
        THEN it should wrap the formula with metadata
        """
        pred = Predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        statement = DCECStatement(formula, label="test1")
        
        assert statement.formula == formula
        assert statement.label == "test1"
        assert "test1" in str(statement)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
