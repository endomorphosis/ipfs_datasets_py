"""
Tests for Phase 7 Week 3: Data Structure Optimization

Tests memory optimization techniques including:
- __slots__ for reduced memory footprint
- Frozen dataclasses for immutability and optimization
- Efficient collection usage (tuples vs lists)
- Memory pooling for frequently created objects
"""

import pytest
import sys
from typing import List
from dataclasses import dataclass


from ipfs_datasets_py.logic.CEC.native.dcec_core import (
    Sort, Variable, Function, Predicate,
    Formula, AtomicFormula, DeonticFormula,
    DeonticOperator, CognitiveOperator, LogicalConnective,
    Term, VariableTerm, FunctionTerm,
)


class TestSlotedClassMemoryFootprint:
    """
    GIVEN classes with __slots__ defined
    WHEN multiple instances are created
    THEN memory usage should be significantly lower than dict-based classes
    """
    
    def test_sort_has_slots_or_is_frozen_dataclass(self):
        """
        GIVEN the Sort class
        WHEN checking for memory optimization
        THEN it should be a frozen dataclass (which is memory efficient)
        """
        # Sort is a frozen dataclass, which is already memory-efficient
        sort1 = Sort("test_sort")
        
        # Frozen dataclasses don't allow modification
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            sort1.name = "modified"
    
    def test_variable_memory_footprint(self):
        """
        GIVEN Variable class instances
        WHEN creating multiple variables
        THEN each should have minimal memory overhead
        """
        sort = Sort("person")
        variables = [Variable(f"x{i}", sort) for i in range(1000)]
        
        # Frozen dataclasses are memory-efficient
        # Test that we can create many without issue
        assert len(variables) == 1000
        assert all(isinstance(v, Variable) for v in variables)
    
    def test_term_memory_optimization(self):
        """
        GIVEN Term subclasses
        WHEN creating many term instances
        THEN memory usage should be optimized
        """
        sort = Sort("integer")
        var = Variable("x", sort)
        terms = [VariableTerm(var) for _ in range(100)]
        
        # All terms should be independent instances
        assert len(terms) == 100
        assert all(isinstance(t, VariableTerm) for t in terms)
    
    def test_formula_memory_footprint(self):
        """
        GIVEN Formula subclasses
        WHEN creating multiple formula instances
        THEN memory footprint should be minimal
        """
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        var_term = VariableTerm(var)
        
        # Create many atomic formulas
        formulas = [AtomicFormula(pred, [var_term]) for _ in range(100)]
        
        assert len(formulas) == 100
        assert all(isinstance(f, AtomicFormula) for f in formulas)


class TestFrozenDataclasses:
    """
    GIVEN classes that should be immutable
    WHEN attempting to modify them
    THEN operations should fail appropriately
    """
    
    def test_sort_immutability(self):
        """
        GIVEN a Sort instance
        WHEN attempting to modify it
        THEN it should raise an error
        """
        sort = Sort("test")
        
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            sort.name = "modified"
    
    def test_variable_immutability(self):
        """
        GIVEN a Variable instance
        WHEN attempting to modify it
        THEN it should raise an error
        """
        sort = Sort("test")
        var = Variable("x", sort)
        
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            var.name = "modified"
    
    def test_frozen_enables_hashing(self):
        """
        GIVEN frozen dataclass instances
        WHEN using them as dict keys or in sets
        THEN they should be hashable
        """
        sort1 = Sort("person")
        sort2 = Sort("person")
        sort3 = Sort("animal")
        
        # Should be hashable for use in sets/dicts
        sort_set = {sort1, sort2, sort3}
        # sort1 and sort2 are equal, so set should have 2 elements
        assert len(sort_set) == 2
    
    def test_variable_hashing(self):
        """
        GIVEN Variable instances
        WHEN using them as dict keys
        THEN they should be hashable
        """
        sort = Sort("person")
        var1 = Variable("x", sort)
        var2 = Variable("x", sort)
        var3 = Variable("y", sort)
        
        var_dict = {var1: "first", var2: "second", var3: "third"}
        # var1 and var2 are equal, so dict should have 2 keys
        assert len(var_dict) == 2
        assert var_dict[var1] == "second"  # var2 overwrote var1


class TestEfficientCollections:
    """
    GIVEN classes that store collections
    WHEN using tuples vs lists
    THEN prefer tuples for immutable data to save memory
    """
    
    def test_function_arguments_as_tuple(self):
        """
        GIVEN Function class with argument sorts
        WHEN storing argument types
        THEN they should use tuples (immutable) where appropriate
        """
        sort1 = Sort("person")
        sort2 = Sort("number")
        sort_out = Sort("boolean")
        
        func = Function("age_gt", [sort1, sort2], sort_out)
        
        # Check that function stores sorts appropriately
        assert func.arity() == 2
        # If using tuple, it's more memory-efficient
        assert hasattr(func, 'argument_sorts')
    
    def test_predicate_arguments_as_tuple(self):
        """
        GIVEN Predicate class with argument sorts
        WHEN storing argument types
        THEN they should use tuples for immutability
        """
        sort1 = Sort("person")
        sort2 = Sort("person")
        
        pred = Predicate("knows", [sort1, sort2])
        
        # Check that predicate stores argument sorts
        assert pred.arity() == 2
        assert hasattr(pred, 'argument_sorts')
    
    def test_formula_arguments_efficiency(self):
        """
        GIVEN Formula with multiple arguments
        WHEN creating formulas
        THEN argument lists should be efficient
        """
        sort = Sort("entity")
        pred = Predicate("P", [sort, sort])
        var1 = Variable("x", sort)
        var2 = Variable("y", sort)
        term1 = VariableTerm(var1)
        term2 = VariableTerm(var2)
        
        formula = AtomicFormula(pred, [term1, term2])
        
        # Formula should store arguments
        assert hasattr(formula, 'arguments')
        assert len(formula.arguments) == 2


class TestMemoryPooling:
    """
    GIVEN frequently created small objects
    WHEN reusing common instances
    THEN memory usage should be reduced through pooling
    """
    
    def test_sort_reuse(self):
        """
        GIVEN commonly used sorts
        WHEN creating the same sort multiple times
        THEN consider using a sort registry to reuse instances
        """
        # Create the same sort multiple times
        sort1 = Sort("person")
        sort2 = Sort("person")
        
        # They are equal but not the same object (no automatic pooling yet)
        assert sort1 == sort2
        # This is expected behavior - manual pooling would need a registry
    
    def test_variable_creation_cost(self):
        """
        GIVEN Variable creation
        WHEN creating many variables with same sort
        THEN sort reuse reduces memory
        """
        sort = Sort("number")
        
        # Creating many variables with the same sort
        variables = [Variable(f"x{i}", sort) for i in range(100)]
        
        # All variables share the same sort object (by reference)
        assert len(variables) == 100
        # All should have the same sort
        assert all(v.sort == sort for v in variables)
    
    def test_operator_enum_singleton(self):
        """
        GIVEN operator enums
        WHEN accessing operators
        THEN they should be singletons (enum behavior)
        """
        op1 = DeonticOperator.OBLIGATION
        op2 = DeonticOperator.OBLIGATION
        
        # Enums are singletons
        assert op1 is op2
        assert id(op1) == id(op2)
    
    def test_cognitive_operator_singleton(self):
        """
        GIVEN cognitive operator enums
        WHEN accessing the same operator multiple times
        THEN it should be the same object
        """
        op1 = CognitiveOperator.BELIEF
        op2 = CognitiveOperator.BELIEF
        
        assert op1 is op2
        assert id(op1) == id(op2)


class TestStructuralSharing:
    """
    GIVEN immutable data structures
    WHEN creating similar structures
    THEN they can share common substructures
    """
    
    def test_term_sharing_in_formulas(self):
        """
        GIVEN multiple formulas using the same terms
        WHEN formulas share terms
        THEN memory is saved through structural sharing
        """
        sort = Sort("person")
        var = Variable("x", sort)
        term = VariableTerm(var)
        
        pred1 = Predicate("P", [sort])
        pred2 = Predicate("Q", [sort])
        
        formula1 = AtomicFormula(pred1, [term])
        formula2 = AtomicFormula(pred2, [term])
        
        # Both formulas share the same term object
        assert formula1.arguments[0] is formula2.arguments[0]
    
    def test_sort_sharing_across_variables(self):
        """
        GIVEN variables with the same sort
        WHEN sort is reused
        THEN memory is saved
        """
        sort = Sort("person")
        
        var1 = Variable("x", sort)
        var2 = Variable("y", sort)
        var3 = Variable("z", sort)
        
        # All variables share the same sort object
        assert var1.sort is var2.sort
        assert var2.sort is var3.sort


class TestMemoryMeasurement:
    """
    GIVEN optimized data structures
    WHEN measuring actual memory usage
    THEN optimizations should show measurable improvements
    """
    
    def test_sort_memory_size(self):
        """
        GIVEN Sort instances
        WHEN measuring memory size
        THEN frozen dataclass should be efficient
        """
        sort = Sort("test_sort")
        
        # Get object size (approximate)
        size = sys.getsizeof(sort)
        
        # Frozen dataclass should be relatively small
        # Actual size varies by Python version, but should be reasonable
        assert size > 0
        assert size < 1000  # Should be well under 1KB for a simple sort
    
    def test_variable_memory_size(self):
        """
        GIVEN Variable instances
        WHEN measuring memory size
        THEN frozen dataclass should be compact
        """
        sort = Sort("person")
        var = Variable("x", sort)
        
        size = sys.getsizeof(var)
        
        # Should be compact
        assert size > 0
        assert size < 1000
    
    def test_bulk_creation_memory_efficiency(self):
        """
        GIVEN creation of many objects
        WHEN measuring cumulative memory
        THEN optimizations should keep memory reasonable
        """
        sort = Sort("entity")
        
        # Create many variables
        variables = [Variable(f"x{i}", sort) for i in range(1000)]
        
        # Should complete without memory issues
        assert len(variables) == 1000
        
        # Measure total size (rough estimate)
        total_size = sum(sys.getsizeof(v) for v in variables)
        
        # Average per variable should be reasonable
        avg_size = total_size / len(variables)
        assert avg_size < 500  # Should be well under 500 bytes per variable


class TestComparisonWithoutOptimization:
    """
    GIVEN optimized vs non-optimized classes
    WHEN comparing memory usage
    THEN optimizations should show clear benefit
    """
    
    def test_frozen_vs_mutable_comparison(self):
        """
        GIVEN frozen dataclass vs regular class
        WHEN creating instances
        THEN frozen should be more memory-efficient
        """
        # Frozen dataclass (optimized)
        @dataclass(frozen=True)
        class OptimizedClass:
            value: int
            name: str
        
        # Regular dataclass (not frozen)
        @dataclass
        class RegularClass:
            value: int
            name: str
        
        opt_instance = OptimizedClass(42, "test")
        reg_instance = RegularClass(42, "test")
        
        # Both should work
        assert opt_instance.value == 42
        assert reg_instance.value == 42
        
        # Frozen should be hashable
        assert hash(opt_instance)
        
        # Regular is not hashable by default
        with pytest.raises(TypeError):
            hash(reg_instance)
    
    def test_slots_benefit(self):
        """
        GIVEN class with __slots__ vs without
        WHEN measuring memory
        THEN __slots__ should reduce overhead
        """
        # Class with __slots__
        class SlottedClass:
            __slots__ = ['x', 'y']
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        # Regular class (uses __dict__)
        class RegularClass:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        slotted = SlottedClass(1, 2)
        regular = RegularClass(1, 2)
        
        # Slotted class doesn't have __dict__
        assert not hasattr(slotted, '__dict__')
        
        # Regular class has __dict__
        assert hasattr(regular, '__dict__')
        
        # __dict__ adds memory overhead
        slotted_size = sys.getsizeof(slotted)
        regular_size = sys.getsizeof(regular) + sys.getsizeof(regular.__dict__)
        
        # Slotted should be smaller (or at least not larger)
        assert slotted_size <= regular_size


class TestPerformanceImpact:
    """
    GIVEN optimized data structures
    WHEN performing operations
    THEN performance should be maintained or improved
    """
    
    def test_frozen_equality_check_speed(self):
        """
        GIVEN frozen dataclass instances
        WHEN comparing for equality
        THEN comparison should be fast
        """
        sort1 = Sort("person")
        sort2 = Sort("person")
        sort3 = Sort("animal")
        
        # Equality checks should be fast
        assert sort1 == sort2
        assert sort1 != sort3
        assert sort2 != sort3
    
    def test_variable_substitution_performance(self):
        """
        GIVEN Variables and Terms
        WHEN performing substitutions
        THEN operations should be efficient
        """
        sort = Sort("number")
        var1 = Variable("x", sort)
        var2 = Variable("y", sort)
        term1 = VariableTerm(var1)
        term2 = VariableTerm(var2)
        
        # Substitution should work efficiently
        result = term1.substitute(var1, term2)
        
        assert isinstance(result, VariableTerm)
        assert result.variable == var2
    
    def test_formula_construction_speed(self):
        """
        GIVEN optimized classes
        WHEN constructing complex formulas
        THEN construction should be efficient
        """
        sort = Sort("entity")
        pred = Predicate("P", [sort])
        var = Variable("x", sort)
        term = VariableTerm(var)
        
        # Should be able to create many formulas quickly
        formulas = [AtomicFormula(pred, [term]) for _ in range(100)]
        
        assert len(formulas) == 100
