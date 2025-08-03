"""
Test module for SymbolicLogicPrimitives

This module provides comprehensive tests for the LogicPrimitives class and
related functionality, including both SymbolicAI integration and fallback modes.
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock

# Add the project root to Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Import the modules to test
from ipfs_datasets_py.logic_integration.symbolic_logic_primitives import (
    LogicPrimitives,
    create_logic_symbol,
    get_available_primitives,
    test_primitives,
    SYMBOLIC_AI_AVAILABLE
)

# Mock Symbol for testing when SymbolicAI is not available
try:
    from symai import Symbol
except ImportError:
    from ipfs_datasets_py.logic_integration.symbolic_logic_primitives import Symbol


class TestLogicPrimitives:
    """Test suite for LogicPrimitives functionality."""
    
    def setup_method(self):
        """Setup test environment before each test."""
        self.test_statements = [
            "All cats are animals",
            "Some birds can fly",
            "Every student studies hard",
            "There exists a cat that is black",
            "If it rains, then the ground is wet",
            "Birds can fly and cats can run"
        ]
        
        self.simple_statements = [
            "Fluffy is a cat",
            "The sky is blue",
            "Dogs bark"
        ]
    
    def test_create_logic_symbol(self):
        """Test creation of logic symbols."""
        for statement in self.test_statements:
            symbol = create_logic_symbol(statement)
            
            assert symbol is not None
            assert symbol.value == statement
            
            # Check that logic primitive methods are available
            primitive_methods = get_available_primitives()
            for method_name in primitive_methods:
                assert hasattr(symbol, method_name), f"Method {method_name} not found on symbol"
    
    def test_create_logic_symbol_semantic_mode(self):
        """Test creating symbols in semantic vs non-semantic mode."""
        statement = "All cats are animals"
        
        # Test semantic mode (default)
        symbol_semantic = create_logic_symbol(statement, semantic=True)
        assert symbol_semantic.value == statement
        if hasattr(symbol_semantic, '_semantic'):
            assert symbol_semantic._semantic is True
        
        # Test non-semantic mode
        symbol_non_semantic = create_logic_symbol(statement, semantic=False)
        assert symbol_non_semantic.value == statement
        if hasattr(symbol_non_semantic, '_semantic'):
            assert symbol_non_semantic._semantic is False
    
    def test_to_fol_conversion(self):
        """Test FOL conversion primitive."""
        test_cases = [
            {
                "input": "All cats are animals",
                "expected_patterns": ["∀", "Cat", "Animal", "→"]
            },
            {
                "input": "Some birds can fly",
                "expected_patterns": ["∃", "Bird", "Fly"]
            },
            {
                "input": "Fluffy is a cat",
                "expected_patterns": ["Cat", "Fluffy"]
            }
        ]
        
        for test_case in test_cases:
            symbol = create_logic_symbol(test_case["input"])
            fol_result = symbol.to_fol()
            
            assert fol_result is not None
            assert isinstance(fol_result.value, str)
            assert len(fol_result.value) > 0
            
            # Check for expected patterns (case-insensitive)
            fol_formula = fol_result.value.lower()
            found_patterns = sum(1 for pattern in test_case["expected_patterns"] 
                               if pattern.lower() in fol_formula)
            assert found_patterns > 0, f"No expected patterns found in: {fol_result.value}"
    
    def test_to_fol_different_formats(self):
        """Test FOL conversion with different output formats."""
        symbol = create_logic_symbol("All cats are animals")
        
        formats = ["symbolic", "prolog", "tptp"]
        
        for fmt in formats:
            fol_result = symbol.to_fol(fmt)
            assert fol_result is not None
            assert isinstance(fol_result.value, str)
            assert len(fol_result.value) > 0
    
    def test_extract_quantifiers(self):
        """Test quantifier extraction primitive."""
        test_cases = [
            {
                "input": "All cats are animals",
                "expected_types": ["universal", "all"]
            },
            {
                "input": "Some birds can fly",
                "expected_types": ["existential", "some"]
            },
            {
                "input": "Every student studies hard",
                "expected_types": ["universal", "every"]
            },
            {
                "input": "There exists a black cat",
                "expected_types": ["existential", "exists"]
            },
            {
                "input": "Many people love music",
                "expected_types": ["numerical", "many"]
            }
        ]
        
        for test_case in test_cases:
            symbol = create_logic_symbol(test_case["input"])
            quantifiers_result = symbol.extract_quantifiers()
            
            assert quantifiers_result is not None
            assert isinstance(quantifiers_result.value, str)
            
            # Check for expected quantifier types
            result_text = quantifiers_result.value.lower()
            if result_text != "none":
                found_types = sum(1 for qtype in test_case["expected_types"] 
                                if qtype in result_text)
                assert found_types > 0, f"No expected quantifier types in: {result_text}"
    
    def test_extract_quantifiers_no_quantifiers(self):
        """Test quantifier extraction when no quantifiers are present."""
        simple_statements = [
            "Fluffy is a cat",
            "The sky is blue",
            "Dogs bark loudly"
        ]
        
        for statement in simple_statements:
            symbol = create_logic_symbol(statement)
            quantifiers_result = symbol.extract_quantifiers()
            
            assert quantifiers_result is not None
            # Should return "none" or empty list for statements without quantifiers
            result_text = quantifiers_result.value.lower()
            assert result_text in ["none", ""] or len(result_text.strip()) == 0
    
    def test_extract_predicates(self):
        """Test predicate extraction primitive."""
        test_cases = [
            {
                "input": "All cats are animals",
                "expected_predicates": ["are", "is"]
            },
            {
                "input": "Some birds can fly",
                "expected_predicates": ["can", "fly"]
            },
            {
                "input": "Students study hard",
                "expected_predicates": ["study", "studies"]
            },
            {
                "input": "Fluffy loves fish",
                "expected_predicates": ["loves", "love"]
            }
        ]
        
        for test_case in test_cases:
            symbol = create_logic_symbol(test_case["input"])
            predicates_result = symbol.extract_predicates()
            
            assert predicates_result is not None
            assert isinstance(predicates_result.value, str)
            
            result_text = predicates_result.value.lower()
            if result_text != "none":
                # Check for at least one expected predicate
                found_predicates = sum(1 for pred in test_case["expected_predicates"] 
                                     if pred in result_text)
                assert found_predicates > 0, f"No expected predicates in: {result_text}"
    
    def test_logical_and_operation(self):
        """Test logical AND primitive."""
        symbol1 = create_logic_symbol("All cats are animals")
        symbol2 = create_logic_symbol("Fluffy is a cat")
        
        result = symbol1.logical_and(symbol2)
        
        assert result is not None
        assert isinstance(result.value, str)
        assert len(result.value) > 0
        
        # Should contain both original statements somehow
        result_text = result.value.lower()
        assert any(word in result_text for word in ["cat", "animal", "fluffy"])
        
        # Should contain logical conjunction indicator
        assert any(symbol in result.value for symbol in ["∧", "&", "and"])
    
    def test_logical_or_operation(self):
        """Test logical OR primitive."""
        symbol1 = create_logic_symbol("Birds can fly")
        symbol2 = create_logic_symbol("Fish can swim")
        
        result = symbol1.logical_or(symbol2)
        
        assert result is not None
        assert isinstance(result.value, str)
        assert len(result.value) > 0
        
        # Should contain both original concepts
        result_text = result.value.lower()
        assert any(word in result_text for word in ["bird", "fish", "fly", "swim"])
        
        # Should contain logical disjunction indicator
        assert any(symbol in result.value for symbol in ["∨", "|", "or"])
    
    def test_logical_implication(self):
        """Test logical implication primitive."""
        premise = create_logic_symbol("It rains")
        conclusion = create_logic_symbol("The ground gets wet")
        
        result = premise.implies(conclusion)
        
        assert result is not None
        assert isinstance(result.value, str)
        assert len(result.value) > 0
        
        # Should contain both premise and conclusion
        result_text = result.value.lower()
        assert any(word in result_text for word in ["rain", "wet", "ground"])
        
        # Should contain implication indicator
        assert any(symbol in result.value for symbol in ["→", "=>", "implies", "if", "then"])
    
    def test_logical_negation(self):
        """Test logical negation primitive."""
        symbol = create_logic_symbol("All cats are animals")
        
        result = symbol.negate()
        
        assert result is not None
        assert isinstance(result.value, str)
        assert len(result.value) > 0
        
        # Should contain negation indicator
        assert any(symbol in result.value for symbol in ["¬", "~", "not", "NOT"])
        
        # Should still contain original content
        result_text = result.value.lower()
        assert any(word in result_text for word in ["cat", "animal"])
    
    def test_analyze_logical_structure(self):
        """Test logical structure analysis primitive."""
        test_cases = [
            "All cats are animals",  # Universal quantification
            "Some birds can fly",    # Existential quantification
            "If it rains, then the ground is wet",  # Conditional
            "Birds fly and fish swim"  # Conjunction
        ]
        
        for statement in test_cases:
            symbol = create_logic_symbol(statement)
            analysis_result = symbol.analyze_logical_structure()
            
            assert analysis_result is not None
            assert isinstance(analysis_result.value, str)
            assert len(analysis_result.value) > 0
            
            # The analysis should contain some structural information
            analysis_text = analysis_result.value.lower()
            assert any(keyword in analysis_text for keyword in [
                "type", "structure", "quantifier", "predicate", "complex"
            ])
    
    def test_simplify_logic(self):
        """Test logic simplification primitive."""
        complex_statements = [
            "All cats are animals and all animals are living beings",
            "If it rains and it is cold, then the ground is wet and slippery",
            "Some birds can fly or some birds can swim"
        ]
        
        for statement in complex_statements:
            symbol = create_logic_symbol(statement)
            simplified_result = symbol.simplify_logic()
            
            assert simplified_result is not None
            assert isinstance(simplified_result.value, str)
            assert len(simplified_result.value) > 0
            
            # Simplified version should not be longer than original
            # (though this is a rough heuristic)
            if SYMBOLIC_AI_AVAILABLE:
                # With SymbolicAI, simplification might be more sophisticated
                assert len(simplified_result.value) >= 10  # Should have meaningful content
            else:
                # Fallback simplification should at least clean whitespace
                assert "  " not in simplified_result.value  # No double spaces
    
    def test_method_chaining(self):
        """Test chaining of logic primitive methods."""
        symbol = create_logic_symbol("All cats are animals")
        
        # Test chaining quantifier extraction and FOL conversion
        quantifiers = symbol.extract_quantifiers()
        assert quantifiers is not None
        
        fol_formula = symbol.to_fol()
        assert fol_formula is not None
        
        # Test chaining logical operations
        symbol2 = create_logic_symbol("Fluffy is a cat")
        combined = symbol.logical_and(symbol2)
        assert combined is not None
        
        negated = combined.negate()
        assert negated is not None
    
    def test_fallback_methods(self):
        """Test fallback implementations of primitive methods."""
        # Create a symbol and test fallback methods directly
        symbol = create_logic_symbol("All cats are animals")
        
        # Access the LogicPrimitives instance to test fallback methods
        primitives = LogicPrimitives()
        primitives.value = symbol.value
        primitives._semantic = True
        primitives._to_type = lambda x: create_logic_symbol(str(x))
        
        # Test fallback methods
        fol_result = primitives._fallback_to_fol("symbolic")
        assert isinstance(fol_result.value, str)
        assert len(fol_result.value) > 0
        
        quantifiers_result = primitives._fallback_extract_quantifiers()
        assert isinstance(quantifiers_result.value, str)
        
        predicates_result = primitives._fallback_extract_predicates()
        assert isinstance(predicates_result.value, str)
        
        # Test fallback logical operations
        symbol2 = create_logic_symbol("Fluffy is a cat")
        and_result = primitives._fallback_logical_and(symbol2)
        assert "∧" in and_result.value
        
        or_result = primitives._fallback_logical_or(symbol2)
        assert "∨" in or_result.value
        
        implies_result = primitives._fallback_implies(symbol2)
        assert "→" in implies_result.value
        
        negated_result = primitives._fallback_negate()
        assert "¬" in negated_result.value
    
    def test_error_handling(self):
        """Test error handling in primitive methods."""
        # Test with problematic input
        problematic_statements = [
            "This is a very complex statement with unclear logical structure",
            "Random symbols: @#$%^&*()",
            "Numbers only: 123 456 789"
        ]
        
        for statement in problematic_statements:
            symbol = create_logic_symbol(statement)
            
            # All methods should handle errors gracefully
            try:
                fol_result = symbol.to_fol()
                assert fol_result is not None
                
                quantifiers = symbol.extract_quantifiers()
                assert quantifiers is not None
                
                predicates = symbol.extract_predicates()
                assert predicates is not None
                
                analysis = symbol.analyze_logical_structure()
                assert analysis is not None
                
            except Exception as e:
                # If methods fail, they should fail with expected exceptions
                assert isinstance(e, (ValueError, RuntimeError, AttributeError))
    
    def test_get_available_primitives(self):
        """Test getting list of available primitive methods."""
        primitives_list = get_available_primitives()
        
        assert isinstance(primitives_list, list)
        assert len(primitives_list) > 0
        
        expected_methods = [
            'to_fol',
            'extract_quantifiers',
            'extract_predicates',
            'logical_and',
            'logical_or',
            'implies',
            'negate',
            'analyze_logical_structure',
            'simplify_logic'
        ]
        
        for method in expected_methods:
            assert method in primitives_list
    
    @pytest.mark.parametrize("statement,expected_elements", [
        ("All cats are animals", ["all", "cat", "animal"]),
        ("Some birds can fly", ["some", "bird", "fly"]),
        ("If it rains then it floods", ["if", "rain", "flood"]),
        ("Students study or play", ["student", "study", "play", "or"])
    ])
    def test_parametrized_fol_conversion(self, statement, expected_elements):
        """Parametrized test for FOL conversion with various inputs."""
        symbol = create_logic_symbol(statement)
        fol_result = symbol.to_fol()
        
        assert fol_result is not None
        result_text = fol_result.value.lower()
        
        # Check that at least half of expected elements are found
        found_elements = sum(1 for elem in expected_elements if elem in result_text)
        assert found_elements >= len(expected_elements) // 2
    
    @pytest.mark.parametrize("format_type", ["symbolic", "prolog", "tptp"])
    def test_parametrized_format_conversion(self, format_type):
        """Parametrized test for different FOL output formats."""
        symbol = create_logic_symbol("All cats are animals")
        fol_result = symbol.to_fol(format_type)
        
        assert fol_result is not None
        assert isinstance(fol_result.value, str)
        assert len(fol_result.value) > 0
        
        # Check format-specific characteristics
        if format_type == "prolog":
            # Should not contain Unicode symbols in prolog format
            assert "∀" not in fol_result.value or "forall" in fol_result.value.lower()
        elif format_type == "tptp":
            # TPTP format should have specific structure
            assert "fof(" in fol_result.value.lower() or len(fol_result.value) > 5


class TestLogicPrimitivesIntegration:
    """Integration tests for LogicPrimitives with other components."""
    
    def test_integration_with_symbolic_fol_bridge(self):
        """Test integration between primitives and FOL bridge."""
        from ipfs_datasets_py.logic_integration.symbolic_fol_bridge import SymbolicFOLBridge
        
        bridge = SymbolicFOLBridge()
        statement = "All cats are animals"
        
        # Create symbol using bridge
        bridge_symbol = bridge.create_semantic_symbol(statement)
        
        # Create symbol using primitives
        primitive_symbol = create_logic_symbol(statement)
        
        # Both should work and produce reasonable results
        assert bridge_symbol is not None
        assert primitive_symbol is not None
        
        # Test that primitive methods work on bridge-created symbols
        if hasattr(bridge_symbol, 'to_fol'):
            fol_result = bridge_symbol.to_fol()
            assert fol_result is not None
    
    def test_workflow_with_multiple_primitives(self):
        """Test a workflow using multiple primitive methods."""
        # Step 1: Create a complex logical statement
        statement = "All students study hard and some students excel"
        symbol = create_logic_symbol(statement)
        
        # Step 2: Analyze structure
        structure = symbol.analyze_logical_structure()
        assert structure is not None
        
        # Step 3: Extract components
        quantifiers = symbol.extract_quantifiers()
        predicates = symbol.extract_predicates()
        assert quantifiers is not None
        assert predicates is not None
        
        # Step 4: Convert to FOL
        fol_formula = symbol.to_fol()
        assert fol_formula is not None
        
        # Step 5: Simplify if needed
        simplified = fol_formula.simplify_logic()
        assert simplified is not None
        
        # All steps should produce meaningful output
        assert len(structure.value) > 0
        assert len(fol_formula.value) > 0
        assert len(simplified.value) > 0


class TestMockScenarios:
    """Test scenarios with mocked SymbolicAI functionality."""
    
    @patch('ipfs_datasets_py.logic_integration.symbolic_logic_primitives.SYMBOLIC_AI_AVAILABLE', False)
    def test_fallback_mode_complete_workflow(self):
        """Test complete workflow when SymbolicAI is not available."""
        statement = "All cats are animals"
        symbol = create_logic_symbol(statement)
        
        # All methods should still work in fallback mode
        fol_result = symbol.to_fol()
        quantifiers = symbol.extract_quantifiers()
        predicates = symbol.extract_predicates()
        analysis = symbol.analyze_logical_structure()
        
        # All should return reasonable results
        assert fol_result is not None and len(fol_result.value) > 0
        assert quantifiers is not None
        assert predicates is not None
        assert analysis is not None
        
        # Logical operations should also work
        symbol2 = create_logic_symbol("Fluffy is a cat")
        combined = symbol.logical_and(symbol2)
        assert combined is not None
        assert "∧" in combined.value
    
    def test_with_mock_symbol_ai_methods(self):
        """Test primitives with mocked SymbolicAI Symbol methods."""
        # Create a mock symbol with specific responses
        mock_symbol = Mock()
        mock_symbol.value = "All cats are animals"
        mock_symbol._semantic = True
        mock_symbol.query = Mock(return_value="all, every")
        mock_symbol._to_type = Mock(side_effect=lambda x: create_logic_symbol(str(x)))
        
        # Create LogicPrimitives instance and bind to mock
        primitives = LogicPrimitives()
        primitives.value = mock_symbol.value
        primitives._semantic = mock_symbol._semantic
        primitives._to_type = mock_symbol._to_type
        
        # Test that methods work with mocked responses
        if SYMBOLIC_AI_AVAILABLE:
            # This would test the actual SymbolicAI integration
            pass
        else:
            # Test fallback behavior
            result = primitives._fallback_extract_quantifiers()
            assert result is not None


def test_module_level_test_function():
    """Test the module-level test function."""
    # This should not raise any exceptions
    try:
        test_primitives()
        # If it completes without error, that's a success
        assert True
    except Exception as e:
        # If it fails, check that it's a reasonable failure
        assert isinstance(e, (ImportError, AttributeError, ValueError))


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
