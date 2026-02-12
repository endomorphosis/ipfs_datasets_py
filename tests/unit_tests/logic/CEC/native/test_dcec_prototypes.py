"""
Tests for DCEC Prototype Namespace Management

Tests the advanced namespace functionality ported from DCEC_Library/prototypes.py
"""

import pytest
from ipfs_datasets_py.logic.CEC.native.dcec_prototypes import DCECPrototypeNamespace


class TestDCECPrototypeNamespace:
    """Tests for DCECPrototypeNamespace class."""
    
    def test_create_empty_namespace(self):
        """GIVEN nothing WHEN creating namespace THEN initialized properly."""
        # GIVEN / WHEN
        ns = DCECPrototypeNamespace()
        
        # THEN
        assert ns.functions == {}
        assert ns.atomics == {}
        assert ns.sorts == {}
        assert "TEMP" in ns.quant_map


class TestSortManagement:
    """Tests for sort (type) management."""
    
    def test_add_simple_sort(self):
        """GIVEN namespace WHEN adding sort THEN sort added."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        
        # WHEN
        result = ns.add_code_sort("Object")
        
        # THEN
        assert result is True
        assert "Object" in ns.sorts
        assert ns.sorts["Object"] == []
    
    def test_add_sort_with_parent(self):
        """GIVEN sort WHEN adding child sort THEN inheritance recorded."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Object")
        
        # WHEN
        result = ns.add_code_sort("Agent", ["Object"])
        
        # THEN
        assert result is True
        assert "Agent" in ns.sorts
        assert "Object" in ns.sorts["Agent"]
    
    def test_add_sort_with_nonexistent_parent(self):
        """GIVEN namespace WHEN adding sort with undefined parent THEN fails."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        
        # WHEN
        result = ns.add_code_sort("Agent", ["NonExistent"])
        
        # THEN
        assert result is False
    
    def test_add_duplicate_sort(self):
        """GIVEN existing sort WHEN adding again THEN succeeds (idempotent)."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Object")
        
        # WHEN
        result = ns.add_code_sort("Object")
        
        # THEN
        assert result is True
    
    def test_add_text_sort_simple(self):
        """GIVEN text expression WHEN adding sort THEN parsed and added."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        
        # WHEN
        result = ns.add_text_sort("(typedef Object)")
        
        # THEN
        assert result is True
        assert "Object" in ns.sorts
    
    def test_add_text_sort_with_parent(self):
        """GIVEN parent exists WHEN adding text sort THEN inheritance works."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Object")
        
        # WHEN
        result = ns.add_text_sort("(typedef Agent Object)")
        
        # THEN
        assert result is True
        assert "Agent" in ns.sorts


class TestFunctionManagement:
    """Tests for function management."""
    
    def test_add_simple_function(self):
        """GIVEN namespace WHEN adding function THEN function added."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Boolean")
        
        # WHEN
        result = ns.add_code_function("and", "Boolean", ["Boolean", "Boolean"])
        
        # THEN
        assert result is True
        assert "and" in ns.functions
        assert ["Boolean", ["Boolean", "Boolean"]] in ns.functions["and"]
    
    def test_add_function_overload(self):
        """GIVEN function WHEN adding overload THEN both signatures stored."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Boolean")
        ns.add_code_sort("Numeric")
        ns.add_code_function("equals", "Boolean", ["Boolean", "Boolean"])
        
        # WHEN
        result = ns.add_code_function("equals", "Boolean", ["Numeric", "Numeric"])
        
        # THEN
        assert result is True
        assert len(ns.functions["equals"]) == 2
    
    def test_add_duplicate_function_signature(self):
        """GIVEN function WHEN adding same signature THEN not duplicated."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Boolean")
        ns.add_code_function("and", "Boolean", ["Boolean", "Boolean"])
        
        # WHEN
        ns.add_code_function("and", "Boolean", ["Boolean", "Boolean"])
        
        # THEN
        assert len(ns.functions["and"]) == 1


class TestAtomicManagement:
    """Tests for atomic (constant) management."""
    
    def test_add_atomic(self):
        """GIVEN sort WHEN adding atomic THEN atomic added."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Agent")
        
        # WHEN
        result = ns.add_code_atomic("john", "Agent")
        
        # THEN
        assert result is True
        assert "john" in ns.atomics
        assert ns.atomics["john"] == "Agent"
    
    def test_find_atomic_type(self):
        """GIVEN atomic WHEN finding type THEN returns type."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Agent")
        ns.add_code_atomic("john", "Agent")
        
        # WHEN
        result = ns.find_atomic_type("john")
        
        # THEN
        assert result == "Agent"
    
    def test_find_nonexistent_atomic(self):
        """GIVEN namespace WHEN finding undefined atomic THEN returns None."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        
        # WHEN
        result = ns.find_atomic_type("nonexistent")
        
        # THEN
        assert result is None
    
    def test_add_conflicting_atomic(self):
        """GIVEN atomic WHEN adding with different type THEN fails."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Agent")
        ns.add_code_sort("Object")
        ns.add_code_atomic("john", "Agent")
        
        # WHEN
        result = ns.add_code_atomic("john", "Object")
        
        # THEN
        assert result is False
    
    def test_add_same_atomic_same_type(self):
        """GIVEN atomic WHEN adding again with same type THEN succeeds."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Agent")
        ns.add_code_atomic("john", "Agent")
        
        # WHEN
        result = ns.add_code_atomic("john", "Agent")
        
        # THEN
        assert result is True


class TestTypeConflictResolution:
    """Tests for type compatibility checking."""
    
    def test_exact_type_match(self):
        """GIVEN same types WHEN checking conflict THEN no conflict."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Agent")
        
        # WHEN
        compatible, distance = ns.no_conflict("Agent", "Agent")
        
        # THEN
        assert compatible is True
        assert distance == 0
    
    def test_wildcard_type(self):
        """GIVEN wildcard WHEN checking THEN always compatible."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Agent")
        
        # WHEN
        compatible, distance = ns.no_conflict("?", "Agent")
        
        # THEN
        assert compatible is True
    
    def test_direct_inheritance(self):
        """GIVEN child type WHEN checking against parent THEN compatible."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Object")
        ns.add_code_sort("Agent", ["Object"])
        
        # WHEN
        compatible, distance = ns.no_conflict("Agent", "Object")
        
        # THEN
        assert compatible is True
        assert distance == 1
    
    def test_indirect_inheritance(self):
        """GIVEN grandchild WHEN checking against grandparent THEN compatible."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Object")
        ns.add_code_sort("Agent", ["Object"])
        ns.add_code_sort("Robot", ["Agent"])
        
        # WHEN
        compatible, distance = ns.no_conflict("Robot", "Object")
        
        # THEN
        assert compatible is True
        assert distance == 2
    
    def test_incompatible_types(self):
        """GIVEN unrelated types WHEN checking THEN not compatible."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Agent")
        ns.add_code_sort("Moment")
        
        # WHEN
        compatible, distance = ns.no_conflict("Agent", "Moment")
        
        # THEN
        assert compatible is False


class TestBasicDCEC:
    """Tests for adding basic DCEC definitions."""
    
    def test_add_basic_dcec(self):
        """GIVEN namespace WHEN adding basic DCEC THEN all added."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        
        # WHEN
        ns.add_basic_dcec()
        
        # THEN
        # Check sorts
        assert "Object" in ns.sorts
        assert "Agent" in ns.sorts
        assert "Moment" in ns.sorts
        assert "Boolean" in ns.sorts
        assert "Event" in ns.sorts
        
        # Check inheritance
        assert "Object" in ns.sorts["Agent"]
        
        # Check functions
        assert "B" in ns.functions  # Belief
        assert "K" in ns.functions  # Knowledge
        assert "O" in ns.functions  # Obligation
        assert "and" in ns.functions
        assert "holds" in ns.functions
    
    def test_add_basic_logic(self):
        """GIVEN namespace WHEN adding basic logic THEN or/xor added."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_basic_dcec()
        
        # WHEN
        ns.add_basic_logic()
        
        # THEN
        assert "or" in ns.functions
        assert "xor" in ns.functions
    
    def test_add_basic_numerics(self):
        """GIVEN namespace WHEN adding numerics THEN arithmetic added."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_basic_dcec()
        
        # WHEN
        ns.add_basic_numerics()
        
        # THEN
        assert "add" in ns.functions
        assert "multiply" in ns.functions
        assert "greater" in ns.functions
        assert "equals" in ns.functions


class TestNamespaceUtilities:
    """Tests for namespace utility functions."""
    
    def test_get_statistics(self):
        """GIVEN populated namespace WHEN getting stats THEN counts returned."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Object")
        ns.add_code_sort("Agent", ["Object"])
        ns.add_code_function("and", "Boolean", ["Boolean", "Boolean"])
        ns.add_code_atomic("john", "Agent")
        
        # WHEN
        stats = ns.get_statistics()
        
        # THEN
        assert stats["sorts"] == 2
        assert stats["functions"] == 1
        assert stats["atomics"] == 1
        assert stats["function_overloads"] == 1
    
    def test_print_namespace(self, capsys):
        """GIVEN namespace WHEN printing THEN output generated."""
        # GIVEN
        ns = DCECPrototypeNamespace()
        ns.add_code_sort("Object")
        ns.add_code_function("and", "Boolean", ["Boolean", "Boolean"])
        ns.add_code_atomic("x", "Object")
        
        # WHEN
        ns.print_namespace()
        
        # THEN
        captured = capsys.readouterr()
        assert "Sorts" in captured.out
        assert "Functions" in captured.out
        assert "Atomics" in captured.out
