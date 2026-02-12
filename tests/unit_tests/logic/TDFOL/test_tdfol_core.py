"""
Tests for TDFOL Core Module

This module tests the core TDFOL data structures following GIVEN-WHEN-THEN format.
"""

import pytest

from ipfs_datasets_py.logic.TDFOL import (
    BinaryFormula,
    Constant,
    DeonticOperator,
    LogicOperator,
    Predicate,
    Quantifier,
    QuantifiedFormula,
    Sort,
    TDFOLKnowledgeBase,
    TemporalOperator,
    Variable,
    create_always,
    create_conjunction,
    create_eventually,
    create_existential,
    create_implication,
    create_negation,
    create_obligation,
    create_permission,
    create_universal,
)


class TestTerms:
    """Test TDFOL terms."""
    
    def test_variable_creation(self):
        """Test creating a variable."""
        # GIVEN a variable name
        name = "x"
        
        # WHEN creating a variable
        var = Variable(name)
        
        # THEN it should have correct properties
        assert var.name == name
        assert var.sort is None
        assert var.get_free_variables() == {name}
    
    def test_constant_creation(self):
        """Test creating a constant."""
        # GIVEN a constant name
        name = "john"
        
        # WHEN creating a constant
        const = Constant(name)
        
        # THEN it should have correct properties
        assert const.name == name
        assert const.get_free_variables() == set()


class TestFormulas:
    """Test TDFOL formulas."""
    
    def test_predicate_creation(self):
        """Test creating a predicate."""
        # GIVEN a predicate name and arguments
        name = "Person"
        arg = Variable("x")
        
        # WHEN creating a predicate
        pred = Predicate(name, (arg,))
        
        # THEN it should have correct properties
        assert pred.name == name
        assert pred.arguments == (arg,)
        assert pred.get_free_variables() == {"x"}
        assert pred.get_predicates() == {"Person"}
    
    def test_implication(self):
        """Test creating an implication."""
        # GIVEN two predicates
        p = Predicate("P", (Variable("x"),))
        q = Predicate("Q", (Variable("x"),))
        
        # WHEN creating implication
        impl = create_implication(p, q)
        
        # THEN it should have correct properties
        assert impl.operator == LogicOperator.IMPLIES
        assert impl.get_free_variables() == {"x"}
    
    def test_negation(self):
        """Test creating a negation."""
        # GIVEN a predicate
        p = Predicate("P", ())
        
        # WHEN creating negation
        neg = create_negation(p)
        
        # THEN it should have correct structure
        assert neg.operator == LogicOperator.NOT
        assert neg.formula == p


class TestQuantifiers:
    """Test quantified formulas."""
    
    def test_universal_quantification(self):
        """Test creating universal quantification."""
        # GIVEN a variable and predicate
        x = Variable("x")
        p = Predicate("Person", (x,))
        
        # WHEN creating universal quantification
        forall = create_universal(x, p)
        
        # THEN it should have correct properties
        assert forall.quantifier == Quantifier.FORALL
        assert forall.variable == x
        assert forall.formula == p
        assert forall.get_free_variables() == set()  # x is bound
    
    def test_existential_quantification(self):
        """Test creating existential quantification."""
        # GIVEN a variable and predicate
        y = Variable("y")
        q = Predicate("Happy", (y,))
        
        # WHEN creating existential quantification
        exists = create_existential(y, q)
        
        # THEN it should have correct properties
        assert exists.quantifier == Quantifier.EXISTS
        assert exists.get_free_variables() == set()  # y is bound


class TestDeonticLogic:
    """Test deontic logic formulas."""
    
    def test_obligation(self):
        """Test creating an obligation."""
        # GIVEN a predicate
        p = Predicate("PayTax", (Variable("x"),))
        
        # WHEN creating obligation
        obligation = create_obligation(p)
        
        # THEN it should have correct properties
        assert obligation.operator == DeonticOperator.OBLIGATION
        assert obligation.formula == p
    
    def test_permission(self):
        """Test creating a permission."""
        # GIVEN a predicate
        p = Predicate("Drive", ())
        
        # WHEN creating permission
        permission = create_permission(p)
        
        # THEN it should have correct properties
        assert permission.operator == DeonticOperator.PERMISSION


class TestTemporalLogic:
    """Test temporal logic formulas."""
    
    def test_always(self):
        """Test creating always formula."""
        # GIVEN a predicate
        p = Predicate("Safe", ())
        
        # WHEN creating always formula
        always = create_always(p)
        
        # THEN it should have correct properties
        assert always.operator == TemporalOperator.ALWAYS
        assert always.formula == p
    
    def test_eventually(self):
        """Test creating eventually formula."""
        # GIVEN a predicate
        p = Predicate("Success", ())
        
        # WHEN creating eventually formula
        eventually = create_eventually(p)
        
        # THEN it should have correct properties
        assert eventually.operator == TemporalOperator.EVENTUALLY


class TestKnowledgeBase:
    """Test TDFOL knowledge base."""
    
    def test_create_knowledge_base(self):
        """Test creating a knowledge base."""
        # WHEN creating a knowledge base
        kb = TDFOLKnowledgeBase()
        
        # THEN it should be empty
        assert len(kb.axioms) == 0
        assert len(kb.theorems) == 0
    
    def test_add_axiom(self):
        """Test adding an axiom."""
        # GIVEN a knowledge base and formula
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        
        # WHEN adding axiom
        kb.add_axiom(p)
        
        # THEN it should be in the knowledge base
        assert p in kb.axioms
    
    def test_get_predicates(self):
        """Test getting all predicates."""
        # GIVEN a knowledge base with formulas
        kb = TDFOLKnowledgeBase()
        p = Predicate("P", ())
        q = Predicate("Q", ())
        kb.add_axiom(p)
        kb.add_axiom(q)
        
        # WHEN getting predicates
        predicates = kb.get_predicates()
        
        # THEN it should include both
        assert predicates == {"P", "Q"}


class TestComplexFormulas:
    """Test complex combined formulas."""
    
    def test_quantified_deontic_formula(self):
        """Test combining quantifiers with deontic operators."""
        # GIVEN a variable and predicates
        x = Variable("x")
        p = Predicate("Person", (x,))
        q = Predicate("PayTax", (x,))
        
        # WHEN creating ∀x.(Person(x) → O(PayTax(x)))
        impl = create_implication(p, create_obligation(q))
        forall = create_universal(x, impl)
        
        # THEN it should have correct structure
        assert isinstance(forall, QuantifiedFormula)
        assert forall.get_free_variables() == set()  # x is bound
    
    def test_temporal_deontic_formula(self):
        """Test combining temporal and deontic operators."""
        # GIVEN a predicate
        p = Predicate("Safe", ())
        
        # WHEN creating O(□P)
        always_p = create_always(p)
        obligation = create_obligation(always_p)
        
        # THEN it should have correct nested structure
        assert obligation.formula == always_p
        assert always_p.formula == p
