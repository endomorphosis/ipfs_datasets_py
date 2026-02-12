"""
Unit tests for native DCEC namespace and container.

These tests validate namespace management and container functionality.
"""

import pytest
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from ipfs_datasets_py.logic.native.dcec_namespace import (
    DCECNamespace,
    DCECContainer,
)
from ipfs_datasets_py.logic.native.dcec_core import (
    Sort,
    Variable,
    Function,
    Predicate,
    VariableTerm,
    AtomicFormula,
    DeonticOperator,
    DeonticFormula,
)


class TestDCECNamespace:
    """Test suite for DCECNamespace."""
    
    def test_namespace_creation(self):
        """
        GIVEN a new namespace
        WHEN creating DCECNamespace
        THEN it should have built-in sorts
        """
        ns = DCECNamespace()
        
        assert "Entity" in ns.sorts
        assert "Agent" in ns.sorts
        assert "Boolean" in ns.sorts
        assert "Moment" in ns.sorts
    
    def test_add_sort(self):
        """
        GIVEN a namespace
        WHEN adding a new sort
        THEN it should be available for lookup
        """
        ns = DCECNamespace()
        
        sort = ns.add_sort("CustomEntity")
        
        assert sort.name == "CustomEntity"
        assert ns.get_sort("CustomEntity") == sort
    
    def test_add_sort_with_parent(self):
        """
        GIVEN a namespace
        WHEN adding a sort with parent
        THEN it should maintain hierarchy
        """
        ns = DCECNamespace()
        
        sort = ns.add_sort("SpecialAgent", parent="Agent")
        
        assert sort.parent == ns.sorts["Agent"]
        assert sort.is_subtype_of(ns.sorts["Agent"])
        assert sort.is_subtype_of(ns.sorts["Entity"])
    
    def test_add_duplicate_sort_fails(self):
        """
        GIVEN a namespace with existing sort
        WHEN adding duplicate sort
        THEN it should raise ValueError
        """
        ns = DCECNamespace()
        ns.add_sort("TestSort")
        
        with pytest.raises(ValueError):
            ns.add_sort("TestSort")
    
    def test_add_variable(self):
        """
        GIVEN a namespace
        WHEN adding a variable
        THEN it should be available
        """
        ns = DCECNamespace()
        
        var = ns.add_variable("x", "Agent")
        
        assert var.name == "x"
        assert var.sort == ns.sorts["Agent"]
        assert ns.get_variable("x") == var
    
    def test_add_variable_invalid_sort(self):
        """
        GIVEN a namespace
        WHEN adding variable with non-existent sort
        THEN it should raise ValueError
        """
        ns = DCECNamespace()
        
        with pytest.raises(ValueError):
            ns.add_variable("x", "NonExistentSort")
    
    def test_add_function(self):
        """
        GIVEN a namespace
        WHEN adding a function
        THEN it should be available
        """
        ns = DCECNamespace()
        
        func = ns.add_function("perform", ["Agent"], "Action")
        
        assert func.name == "perform"
        assert func.arity() == 1
        assert ns.get_function("perform") == func
    
    def test_add_predicate(self):
        """
        GIVEN a namespace
        WHEN adding a predicate
        THEN it should be available
        """
        ns = DCECNamespace()
        
        pred = ns.add_predicate("isHonest", ["Agent"])
        
        assert pred.name == "isHonest"
        assert pred.arity() == 1
        assert ns.get_predicate("isHonest") == pred
    
    def test_namespace_statistics(self):
        """
        GIVEN a namespace with symbols
        WHEN getting statistics
        THEN it should reflect counts
        """
        ns = DCECNamespace()
        initial_sorts = ns.get_statistics()["sorts"]
        
        ns.add_sort("Custom1")
        ns.add_variable("x", "Agent")
        ns.add_function("f", ["Agent"], "Action")
        ns.add_predicate("p", ["Agent"])
        
        stats = ns.get_statistics()
        
        assert stats["sorts"] == initial_sorts + 1
        assert stats["variables"] == 1
        assert stats["functions"] == 1
        assert stats["predicates"] == 1
    
    def test_namespace_repr(self):
        """
        GIVEN a namespace
        WHEN getting string representation
        THEN it should show statistics
        """
        ns = DCECNamespace()
        repr_str = repr(ns)
        
        assert "DCECNamespace" in repr_str
        assert "sorts=" in repr_str


class TestDCECContainer:
    """Test suite for DCECContainer."""
    
    def test_container_creation(self):
        """
        GIVEN a new container
        WHEN creating DCECContainer
        THEN it should have empty state with namespace
        """
        container = DCECContainer()
        
        assert container.namespace is not None
        assert len(container.statements) == 0
        assert len(container.axioms) == 0
        assert len(container.theorems) == 0
    
    def test_add_statement(self):
        """
        GIVEN a container and formula
        WHEN adding a statement
        THEN it should be stored
        """
        container = DCECContainer()
        
        # Create simple formula
        pred = container.namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        stmt = container.add_statement(formula)
        
        assert stmt.formula == formula
        assert stmt in container.statements
    
    def test_add_statement_with_label(self):
        """
        GIVEN a container
        WHEN adding statement with label
        THEN it should be retrievable by label
        """
        container = DCECContainer()
        
        pred = container.namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        stmt = container.add_statement(formula, label="test1")
        
        assert stmt.label == "test1"
        assert container.get_statement("test1") == stmt
    
    def test_add_duplicate_label_fails(self):
        """
        GIVEN a container with labeled statement
        WHEN adding statement with same label
        THEN it should raise ValueError
        """
        container = DCECContainer()
        
        pred = container.namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        container.add_statement(formula, label="test1")
        
        with pytest.raises(ValueError):
            container.add_statement(formula, label="test1")
    
    def test_add_axiom(self):
        """
        GIVEN a container
        WHEN adding statement as axiom
        THEN it should be in axioms list
        """
        container = DCECContainer()
        
        pred = container.namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        stmt = container.add_statement(formula, is_axiom=True)
        
        assert stmt in container.axioms
    
    def test_add_theorem(self):
        """
        GIVEN a container
        WHEN adding a theorem
        THEN it should be in theorems list
        """
        container = DCECContainer()
        
        pred = container.namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        stmt = container.add_theorem(formula)
        
        assert stmt in container.theorems
    
    def test_get_all_statements(self):
        """
        GIVEN a container with statements
        WHEN getting all statements
        THEN it should return copy of list
        """
        container = DCECContainer()
        
        pred = container.namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        container.add_statement(formula)
        container.add_statement(formula)
        
        statements = container.get_all_statements()
        
        assert len(statements) == 2
        # Verify it's a copy
        statements.clear()
        assert len(container.statements) == 2
    
    def test_clear_statements(self):
        """
        GIVEN a container with statements
        WHEN clearing
        THEN all statements should be removed
        """
        container = DCECContainer()
        
        pred = container.namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        container.add_statement(formula, label="test1")
        container.add_axiom(formula, label="axiom1")
        
        container.clear()
        
        assert len(container.statements) == 0
        assert len(container.axioms) == 0
        assert len(container.statement_labels) == 0
        # Namespace should still exist
        assert container.namespace is not None
    
    def test_container_statistics(self):
        """
        GIVEN a container with various statements
        WHEN getting statistics
        THEN it should reflect all counts
        """
        container = DCECContainer()
        
        pred = container.namespace.add_predicate("test", [])
        formula = AtomicFormula(pred, [])
        
        container.add_statement(formula, label="s1")
        container.add_statement(formula, is_axiom=True, label="ax1")
        container.add_theorem(formula, label="th1")
        
        stats = container.get_statistics()
        
        assert stats["total_statements"] == 3
        assert stats["axioms"] == 1
        assert stats["theorems"] == 1
        assert stats["labeled_statements"] == 3
    
    def test_container_repr(self):
        """
        GIVEN a container
        WHEN getting string representation
        THEN it should show counts
        """
        container = DCECContainer()
        repr_str = repr(container)
        
        assert "DCECContainer" in repr_str
        assert "statements=" in repr_str


class TestIntegration:
    """Integration tests for namespace and container."""
    
    def test_complete_workflow(self):
        """
        GIVEN a complete DCEC workflow
        WHEN creating formulas and adding to container
        THEN everything should work together
        """
        # Create container
        container = DCECContainer()
        
        # Add custom sort
        container.namespace.add_sort("Robot", parent="Agent")
        
        # Add predicates and variables
        pred = container.namespace.add_predicate("shouldAct", ["Robot"])
        x = container.namespace.add_variable("robot1", "Robot")
        
        # Build formula: O(shouldAct(robot1))
        term_x = VariableTerm(x)
        base_formula = AtomicFormula(pred, [term_x])
        deontic_formula = DeonticFormula(DeonticOperator.OBLIGATION, base_formula)
        
        # Add as axiom
        stmt = container.add_statement(
            deontic_formula,
            label="robot_obligation",
            is_axiom=True
        )
        
        # Verify everything
        assert "O" in str(stmt)
        assert "shouldAct" in str(stmt)
        assert stmt in container.axioms
        assert container.get_statement("robot_obligation") == stmt
        
        stats = container.get_statistics()
        assert stats["total_statements"] == 1
        assert stats["axioms"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
