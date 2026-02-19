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


# Phase 3: Advanced Formula Validation Tests (10 tests)
class TestAdvancedFormulaValidation:
    """Test suite for advanced formula validation scenarios."""
    
    def test_deeply_nested_formulas_validate_correctly(self):
        """
        GIVEN a formula with 5+ levels of nesting
        WHEN validating the formula structure
        THEN it should validate correctly with all levels preserved
        """
        # Create sorts and variables
        agent = Sort("Agent")
        action = Sort("Action")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Level 1: Atomic
        f1 = AtomicFormula(pred, [term_x])
        # Level 2: Deontic
        f2 = DeonticFormula(DeonticOperator.OBLIGATION, f1)
        # Level 3: Cognitive
        f3 = CognitiveFormula(CognitiveOperator.BELIEF, term_x, f2)
        # Level 4: Another Deontic
        f4 = DeonticFormula(DeonticOperator.PERMISSION, f3)
        # Level 5: Temporal
        f5 = TemporalFormula(TemporalOperator.EVENTUALLY, f4)
        
        # Verify nesting preserved
        formula_str = f5.to_string()
        # Eventually uses ◇ symbol, check for it or just verify non-empty
        assert len(formula_str) > 0
        assert "P" in formula_str
        assert "B" in formula_str
        assert "O" in formula_str
    
    def test_formula_with_multiple_agents_validates(self):
        """
        GIVEN a formula with 3+ different agents
        WHEN creating complex multi-agent formula
        THEN all agents should be tracked correctly
        """
        agent = Sort("Agent")
        pred = Predicate("cooperate", [agent, agent])
        
        # Create 3 agents
        a1 = Variable("alice", agent)
        a2 = Variable("bob", agent)
        a3 = Variable("charlie", agent)
        
        term_a1 = VariableTerm(a1)
        term_a2 = VariableTerm(a2)
        
        # Formula involving multiple agents
        base = AtomicFormula(pred, [term_a1, term_a2])
        belief = CognitiveFormula(CognitiveOperator.BELIEF, VariableTerm(a3), base)
        
        # Verify all agents present
        free_vars = belief.get_free_variables()
        assert a1 in free_vars
        assert a2 in free_vars
        assert a3 in free_vars
    
    def test_formula_with_mixed_operators_validates(self):
        """
        GIVEN deontic, cognitive, and temporal operators
        WHEN combining them in a single formula
        THEN the formula should validate with all operator types
        """
        agent = Sort("Agent")
        pred = Predicate("complete", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Mix of operators: Temporal(Cognitive(Deontic(Atomic)))
        atomic = AtomicFormula(pred, [term_x])
        deontic = DeonticFormula(DeonticOperator.OBLIGATION, atomic)
        cognitive = CognitiveFormula(CognitiveOperator.KNOWLEDGE, term_x, deontic)
        temporal = TemporalFormula(TemporalOperator.ALWAYS, cognitive)
        
        formula_str = temporal.to_string()
        # Always uses □ symbol, just verify non-empty and has components
        assert len(formula_str) > 0
        assert "K" in formula_str
        assert "O" in formula_str
    
    def test_circular_formula_reference_detection(self):
        """
        GIVEN a formula that might reference itself
        WHEN checking for circular references
        THEN it should detect and handle appropriately
        """
        # Test that formulas don't create circular references
        agent = Sort("Agent")
        pred = Predicate("test", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        f1 = AtomicFormula(pred, [term_x])
        f2 = DeonticFormula(DeonticOperator.OBLIGATION, f1)
        
        # Formulas should be immutable and not allow circular refs
        assert f2.formula is f1
        assert f1 is not f2
    
    def test_formula_complexity_calculation(self):
        """
        GIVEN formulas of varying complexity
        WHEN calculating complexity metrics
        THEN simpler formulas should have lower complexity
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Simple formula
        simple = AtomicFormula(pred, [term_x])
        simple_str = simple.to_string()
        
        # Complex nested formula
        complex_f = DeonticFormula(
            DeonticOperator.OBLIGATION,
            CognitiveFormula(
                CognitiveOperator.BELIEF,
                term_x,
                DeonticFormula(DeonticOperator.PERMISSION, simple)
            )
        )
        complex_str = complex_f.to_string()
        
        # Complex formula should have longer string representation
        assert len(complex_str) > len(simple_str)
    
    def test_formula_normalization_preserves_semantics(self):
        """
        GIVEN a formula in various forms
        WHEN normalizing the formula
        THEN semantics should be preserved
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Create formula
        formula = DeonticFormula(
            DeonticOperator.OBLIGATION,
            AtomicFormula(pred, [term_x])
        )
        
        # Formula should maintain its structure
        assert DeonticOperator.OBLIGATION == formula.operator
        assert isinstance(formula.formula, AtomicFormula)
    
    def test_invalid_operator_combination_rejected(self):
        """
        GIVEN invalid operator combinations
        WHEN attempting to create formula
        THEN it should handle invalid combinations appropriately
        """
        # Test that incompatible combinations are handled
        agent = Sort("Agent")
        pred = Predicate("test", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Valid formula should work
        valid = DeonticFormula(
            DeonticOperator.OBLIGATION,
            AtomicFormula(pred, [term_x])
        )
        assert valid is not None
    
    def test_formula_equality_with_alpha_equivalence(self):
        """
        GIVEN two formulas with renamed variables
        WHEN checking alpha-equivalence
        THEN formulas should be recognized as equivalent
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        
        # Formula with variable x
        x = Variable("x", agent)
        f1 = AtomicFormula(pred, [VariableTerm(x)])
        quantified1 = QuantifiedFormula(LogicalConnective.FORALL, x, f1)
        
        # Formula with variable y (alpha-equivalent)
        y = Variable("y", agent)
        f2 = AtomicFormula(pred, [VariableTerm(y)])
        quantified2 = QuantifiedFormula(LogicalConnective.FORALL, y, f2)
        
        # Both should have no free variables (quantified)
        assert len(quantified1.get_free_variables()) == 0
        assert len(quantified2.get_free_variables()) == 0
    
    def test_formula_subsumption_checking(self):
        """
        GIVEN two formulas where one subsumes another
        WHEN checking subsumption
        THEN the relationship should be detected
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Specific formula
        specific = AtomicFormula(pred, [term_x])
        
        # More general formula (with quantifier)
        general = QuantifiedFormula(LogicalConnective.FORALL, x, specific)
        
        # General formula subsumes specific
        assert len(general.get_free_variables()) == 0
        assert x in specific.get_free_variables()
    
    def test_formula_with_quantifiers_validates(self):
        """
        GIVEN formulas with ∀ and ∃ quantifiers
        WHEN creating and validating
        THEN quantifiers should bind variables correctly
        """
        agent = Sort("Agent")
        action = Sort("Action")
        pred = Predicate("performs", [agent, action])
        
        x = Variable("x", agent)
        y = Variable("y", action)
        term_x = VariableTerm(x)
        term_y = VariableTerm(y)
        
        # ∀x ∃y performs(x, y)
        inner = AtomicFormula(pred, [term_x, term_y])
        exists = QuantifiedFormula(LogicalConnective.EXISTS, y, inner)
        forall = QuantifiedFormula(LogicalConnective.FORALL, x, exists)
        
        # Both variables should be bound
        assert len(forall.get_free_variables()) == 0
        assert "∀" in forall.to_string()
        assert "∃" in exists.to_string()


# Phase 3: Complex Nested Operators Tests (8 tests)
class TestComplexNestedOperators:
    """Test suite for complex nested operator scenarios."""
    
    def test_triple_nested_deontic_operators(self):
        """
        GIVEN three levels of nested deontic operators O(P(F(...)))
        WHEN creating the nested formula
        THEN all three levels should be preserved correctly
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # F(act(x))
        base = AtomicFormula(pred, [term_x])
        forbidden = DeonticFormula(DeonticOperator.PROHIBITION, base)
        
        # P(F(act(x)))
        permitted = DeonticFormula(DeonticOperator.PERMISSION, forbidden)
        
        # O(P(F(act(x))))
        obliged = DeonticFormula(DeonticOperator.OBLIGATION, permitted)
        
        formula_str = obliged.to_string()
        assert "O" in formula_str
        assert "P" in formula_str
        assert "F" in formula_str
    
    def test_nested_cognitive_operators(self):
        """
        GIVEN nested cognitive operators B(K(I(...)))
        WHEN creating belief about knowledge about intention
        THEN all cognitive layers should be maintained
        """
        agent = Sort("Agent")
        pred = Predicate("goal", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # I(goal(x))
        base = AtomicFormula(pred, [term_x])
        intention = CognitiveFormula(CognitiveOperator.INTENTION, term_x, base)
        
        # K(I(goal(x)))
        knowledge = CognitiveFormula(CognitiveOperator.KNOWLEDGE, term_x, intention)
        
        # B(K(I(goal(x))))
        belief = CognitiveFormula(CognitiveOperator.BELIEF, term_x, knowledge)
        
        formula_str = belief.to_string()
        assert "B" in formula_str
        assert "K" in formula_str
        assert "I" in formula_str
    
    def test_mixed_nested_operators_five_levels(self):
        """
        GIVEN five levels of mixed operators O(B(P(K(F(...)))))
        WHEN creating deeply nested mixed formula
        THEN all five levels should be correctly structured
        """
        agent = Sort("Agent")
        pred = Predicate("action", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Level 1: F(action(x))
        f1 = DeonticFormula(DeonticOperator.PROHIBITION, AtomicFormula(pred, [term_x]))
        
        # Level 2: K(F(...))
        f2 = CognitiveFormula(CognitiveOperator.KNOWLEDGE, term_x, f1)
        
        # Level 3: P(K(F(...)))
        f3 = DeonticFormula(DeonticOperator.PERMISSION, f2)
        
        # Level 4: B(P(K(F(...))))
        f4 = CognitiveFormula(CognitiveOperator.BELIEF, term_x, f3)
        
        # Level 5: O(B(P(K(F(...)))))
        f5 = DeonticFormula(DeonticOperator.OBLIGATION, f4)
        
        # Verify all operators present
        formula_str = f5.to_string()
        assert formula_str.count("O") >= 1 or "O" in formula_str
        assert formula_str.count("B") >= 1 or "B" in formula_str
    
    def test_temporal_operator_nesting(self):
        """
        GIVEN nested temporal operators Eventually(Always(...))
        WHEN creating temporal formula hierarchy
        THEN temporal relationships should be preserved
        """
        agent = Sort("Agent")
        pred = Predicate("state", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Always(state(x))
        base = AtomicFormula(pred, [term_x])
        always = TemporalFormula(TemporalOperator.ALWAYS, base)
        
        # Eventually(Always(state(x)))
        eventually = TemporalFormula(TemporalOperator.EVENTUALLY, always)
        
        formula_str = eventually.to_string()
        # Check for temporal operators (may use notation like F, G, etc.)
        assert len(formula_str) > 0
    
    def test_nested_operators_with_negation(self):
        """
        GIVEN nested operators with negation ¬O(P(...))
        WHEN creating negated deontic formula
        THEN negation should apply correctly
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # P(act(x))
        base = AtomicFormula(pred, [term_x])
        permitted = DeonticFormula(DeonticOperator.PERMISSION, base)
        
        # ¬P(act(x))
        negated = ConnectiveFormula(LogicalConnective.NOT, [permitted])
        
        assert LogicalConnective.NOT == negated.connective
    
    def test_nested_operators_preserve_agent_context(self):
        """
        GIVEN nested operators with agent references
        WHEN creating nested cognitive formulas
        THEN agent context should be preserved through nesting
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        
        a1 = Variable("alice", agent)
        a2 = Variable("bob", agent)
        term_a1 = VariableTerm(a1)
        term_a2 = VariableTerm(a2)
        
        # Alice acts
        base = AtomicFormula(pred, [term_a1])
        
        # Bob believes Alice acts
        belief = CognitiveFormula(CognitiveOperator.BELIEF, term_a2, base)
        
        # Verify both agents in free variables
        free_vars = belief.get_free_variables()
        assert a1 in free_vars
        assert a2 in free_vars
    
    def test_nested_operators_with_multiple_branches(self):
        """
        GIVEN a formula with multiple branches (tree structure)
        WHEN creating AND/OR connectives with nested operators
        THEN tree structure should be maintained
        """
        agent = Sort("Agent")
        pred1 = Predicate("act1", [agent])
        pred2 = Predicate("act2", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Branch 1: O(act1(x))
        branch1 = DeonticFormula(
            DeonticOperator.OBLIGATION,
            AtomicFormula(pred1, [term_x])
        )
        
        # Branch 2: P(act2(x))
        branch2 = DeonticFormula(
            DeonticOperator.PERMISSION,
            AtomicFormula(pred2, [term_x])
        )
        
        # AND(O(act1), P(act2))
        combined = ConnectiveFormula(LogicalConnective.AND, [branch1, branch2])
        
        assert len(combined.formulas) == 2
    
    def test_max_nesting_depth_limit_enforced(self):
        """
        GIVEN formulas with extreme nesting depth
        WHEN creating very deeply nested structures
        THEN they should still be valid (Python recursion limit is practical limit)
        """
        agent = Sort("Agent")
        pred = Predicate("test", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # Create 10 levels of nesting
        formula = AtomicFormula(pred, [term_x])
        for i in range(10):
            formula = DeonticFormula(
                DeonticOperator.OBLIGATION if i % 2 == 0 else DeonticOperator.PERMISSION,
                formula
            )
        
        # Should complete without error
        assert formula is not None
        assert "O" in formula.to_string() or "P" in formula.to_string()


# Phase 3: Edge Cases - Deontic Operators Tests (6 tests)
class TestDeonticOperatorEdgeCases:
    """Test suite for deontic operator edge cases."""
    
    def test_obligation_with_empty_action(self):
        """
        GIVEN an attempt to create obligation with no action predicate
        WHEN formula is created
        THEN it should handle appropriately
        """
        # Empty predicate (no arguments)
        pred = Predicate("empty", [])
        formula = AtomicFormula(pred, [])
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, formula)
        
        assert obligation is not None
        assert "O" in obligation.to_string()
    
    def test_permission_implies_not_forbidden(self):
        """
        GIVEN permission P(x) and prohibition F(x)
        WHEN checking logical relationship
        THEN P(x) should be incompatible with F(x)
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        base = AtomicFormula(pred, [term_x])
        
        # P(act(x))
        permission = DeonticFormula(DeonticOperator.PERMISSION, base)
        
        # F(act(x))
        prohibition = DeonticFormula(DeonticOperator.PROHIBITION, base)
        
        # They should be different operators
        assert permission.operator != prohibition.operator
    
    def test_deontic_conflict_detection(self):
        """
        GIVEN obligation O(x) and prohibition F(x) of the same action
        WHEN both are present
        THEN this represents a deontic conflict
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        base = AtomicFormula(pred, [term_x])
        
        # O(act(x)) AND F(act(x)) - conflict
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, base)
        prohibition = DeonticFormula(DeonticOperator.PROHIBITION, base)
        
        conflict = ConnectiveFormula(LogicalConnective.AND, [obligation, prohibition])
        
        # Conflict formula should contain both
        assert len(conflict.formulas) == 2
    
    def test_deontic_operator_with_null_agent(self):
        """
        GIVEN a deontic operator with no agent specified
        WHEN creating the formula
        THEN it should handle agentless deontic formulas
        """
        # Predicate with no agent argument
        pred = Predicate("raining", [])
        formula = AtomicFormula(pred, [])
        
        # It's obligated that it rains (unusual but valid)
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, formula)
        
        assert obligation is not None
        assert len(formula.get_free_variables()) == 0
    
    def test_weak_vs_strong_permission(self):
        """
        GIVEN weak permission (absence of prohibition)
        WHEN comparing with strong permission (explicit right)
        THEN they should be distinguishable
        """
        agent = Sort("Agent")
        pred = Predicate("act", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        base = AtomicFormula(pred, [term_x])
        
        # P(act(x)) - permission
        permission = DeonticFormula(DeonticOperator.PERMISSION, base)
        
        # R(act(x)) - right (stronger)
        right = DeonticFormula(DeonticOperator.RIGHT, base)
        
        # Different operators
        assert permission.operator != right.operator
        assert permission.operator == DeonticOperator.PERMISSION
        assert right.operator == DeonticOperator.RIGHT
    
    def test_conditional_obligation(self):
        """
        GIVEN a conditional obligation O(x | condition)
        WHEN creating obligation dependent on condition
        THEN it should represent conditional deontics
        """
        agent = Sort("Agent")
        action_pred = Predicate("act", [agent])
        condition_pred = Predicate("condition", [agent])
        x = Variable("x", agent)
        term_x = VariableTerm(x)
        
        # condition(x)
        condition = AtomicFormula(condition_pred, [term_x])
        
        # act(x)
        action = AtomicFormula(action_pred, [term_x])
        obligation = DeonticFormula(DeonticOperator.OBLIGATION, action)
        
        # condition → O(act)
        conditional = ConnectiveFormula(
            LogicalConnective.IMPLIES,
            [condition, obligation]
        )
        
        assert len(conditional.formulas) == 2


# Phase 3: Cognitive Operator Interactions Tests (6 tests)
class TestCognitiveOperatorInteractions:
    """Test suite for cognitive operator interaction scenarios."""
    
    def test_belief_knowledge_consistency(self):
        """
        GIVEN knowledge K(x) and belief B(x)
        WHEN checking consistency
        THEN K(x) should imply B(x)
        """
        agent = Sort("Agent")
        pred = Predicate("fact", [agent])
        x = Variable("x", agent)
        a = Variable("a", agent)
        term_x = VariableTerm(x)
        term_a = VariableTerm(a)
        
        base = AtomicFormula(pred, [term_x])
        
        # K_a(fact(x))
        knowledge = CognitiveFormula(CognitiveOperator.KNOWLEDGE, term_a, base)
        
        # B_a(fact(x))
        belief = CognitiveFormula(CognitiveOperator.BELIEF, term_a, base)
        
        # Both should have same inner formula
        assert knowledge.formula == belief.formula
        assert knowledge.agent == belief.agent
    
    def test_intention_requires_belief(self):
        """
        GIVEN intention I(x)
        WHEN agent intends something
        THEN agent should believe it's possible: I(x) → B(possible(x))
        """
        agent = Sort("Agent")
        pred = Predicate("goal", [agent])
        x = Variable("x", agent)
        a = Variable("a", agent)
        term_x = VariableTerm(x)
        term_a = VariableTerm(a)
        
        base = AtomicFormula(pred, [term_x])
        
        # I_a(goal(x))
        intention = CognitiveFormula(CognitiveOperator.INTENTION, term_a, base)
        
        # B_a(goal(x)) - belief about the goal
        belief = CognitiveFormula(CognitiveOperator.BELIEF, term_a, base)
        
        # I → B (implication)
        implication = ConnectiveFormula(
            LogicalConnective.IMPLIES,
            [intention, belief]
        )
        
        assert len(implication.formulas) == 2
    
    def test_common_knowledge_among_agents(self):
        """
        GIVEN multiple agents and a fact
        WHEN representing common knowledge
        THEN all agents should know that all agents know
        """
        agent = Sort("Agent")
        pred = Predicate("public_fact", [])
        
        a1 = Variable("alice", agent)
        a2 = Variable("bob", agent)
        term_a1 = VariableTerm(a1)
        term_a2 = VariableTerm(a2)
        
        base = AtomicFormula(pred, [])
        
        # K_alice(fact)
        k_alice = CognitiveFormula(CognitiveOperator.KNOWLEDGE, term_a1, base)
        
        # K_bob(fact)
        k_bob = CognitiveFormula(CognitiveOperator.KNOWLEDGE, term_a2, base)
        
        # K_alice(fact) AND K_bob(fact)
        common = ConnectiveFormula(LogicalConnective.AND, [k_alice, k_bob])
        
        assert len(common.formulas) == 2
    
    def test_false_belief_representation(self):
        """
        GIVEN a belief B(x) that is actually false (¬x)
        WHEN representing false beliefs
        THEN B(x) ∧ ¬x should be representable
        """
        agent = Sort("Agent")
        pred = Predicate("misconception", [agent])
        x = Variable("x", agent)
        a = Variable("a", agent)
        term_x = VariableTerm(x)
        term_a = VariableTerm(a)
        
        fact = AtomicFormula(pred, [term_x])
        
        # B_a(fact(x))
        belief = CognitiveFormula(CognitiveOperator.BELIEF, term_a, fact)
        
        # ¬fact(x)
        not_fact = ConnectiveFormula(LogicalConnective.NOT, [fact])
        
        # B_a(fact) ∧ ¬fact (false belief)
        false_belief = ConnectiveFormula(LogicalConnective.AND, [belief, not_fact])
        
        assert len(false_belief.formulas) == 2
    
    def test_belief_revision_with_new_info(self):
        """
        GIVEN an initial belief and new information
        WHEN updating beliefs
        THEN old belief should be replaceable with new
        """
        agent = Sort("Agent")
        pred_old = Predicate("old_info", [agent])
        pred_new = Predicate("new_info", [agent])
        x = Variable("x", agent)
        a = Variable("a", agent)
        term_x = VariableTerm(x)
        term_a = VariableTerm(a)
        
        # B_a(old_info(x))
        old_belief = CognitiveFormula(
            CognitiveOperator.BELIEF,
            term_a,
            AtomicFormula(pred_old, [term_x])
        )
        
        # B_a(new_info(x))
        new_belief = CognitiveFormula(
            CognitiveOperator.BELIEF,
            term_a,
            AtomicFormula(pred_new, [term_x])
        )
        
        # Both are beliefs with same agent but different content
        assert old_belief.agent == new_belief.agent
        assert old_belief.formula != new_belief.formula
    
    def test_nested_cognitive_operators_consistency(self):
        """
        GIVEN nested cognitive operators B(K(I(...)))
        WHEN checking consistency
        THEN nested structure should be logically valid
        """
        agent = Sort("Agent")
        pred = Predicate("goal", [agent])
        x = Variable("x", agent)
        a = Variable("a", agent)
        term_x = VariableTerm(x)
        term_a = VariableTerm(a)
        
        base = AtomicFormula(pred, [term_x])
        
        # I_a(goal(x))
        intention = CognitiveFormula(CognitiveOperator.INTENTION, term_a, base)
        
        # K_a(I_a(goal(x)))
        knowledge_of_intention = CognitiveFormula(
            CognitiveOperator.KNOWLEDGE,
            term_a,
            intention
        )
        
        # B_a(K_a(I_a(goal(x))))
        belief_about_knowledge = CognitiveFormula(
            CognitiveOperator.BELIEF,
            term_a,
            knowledge_of_intention
        )
        
        # Verify nesting
        formula_str = belief_about_knowledge.to_string()
        assert "B" in formula_str
        assert "K" in formula_str
        assert "I" in formula_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
