"""
Test module for SymbolicFOLBridge

This module provides comprehensive tests for the SymbolicFOLBridge class,
covering both SymbolicAI integration and fallback functionality.
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

# Add the project root to Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Import the modules to test
from ipfs_datasets_py.logic_integration.symbolic_fol_bridge import (
    SymbolicFOLBridge,
    LogicalComponents,
    FOLConversionResult,
    SYMBOLIC_AI_AVAILABLE
)


class TestSymbolicFOLBridge:
    """Test suite for SymbolicFOLBridge functionality."""
    
    def setup_method(self):
        """Setup test environment before each test."""
        self.bridge = SymbolicFOLBridge(
            confidence_threshold=0.7,
            fallback_enabled=True,
            enable_caching=True
        )
        
        # Test data
        self.test_statements = [
            "All cats are animals",
            "Some birds can fly",
            "If it rains, then the ground is wet",
            "Every student studies hard",
            "Fluffy is a cat",
            "There exists a cat that is black"
        ]
        
        self.invalid_statements = [
            "",
            "   ",
            "a",
            "12345"
        ]
    
    def test_initialization(self):
        """Test SymbolicFOLBridge initialization."""
        # Test default initialization
        bridge = SymbolicFOLBridge()
        assert bridge.confidence_threshold == 0.7
        assert bridge.fallback_enabled is True
        assert bridge.enable_caching is True
        assert isinstance(bridge._cache, dict)
        assert len(bridge._cache) == 0
        
        # Test custom initialization
        bridge_custom = SymbolicFOLBridge(
            confidence_threshold=0.8,
            fallback_enabled=False,
            enable_caching=False
        )
        assert bridge_custom.confidence_threshold == 0.8
        assert bridge_custom.fallback_enabled is False
        assert bridge_custom.enable_caching is False
    
    def test_create_semantic_symbol_valid_input(self):
        """Test creating semantic symbols with valid input."""
        for statement in self.test_statements:
            symbol = self.bridge.create_semantic_symbol(statement)
            
            assert symbol is not None
            assert symbol.value == statement
            # If SymbolicAI is available, check semantic mode
            if hasattr(symbol, '_semantic'):
                assert symbol._semantic is True
    
    def test_create_semantic_symbol_invalid_input(self):
        """Test creating semantic symbols with invalid input."""
        for invalid_statement in self.invalid_statements:
            with pytest.raises(ValueError, match="Text cannot be empty"):
                self.bridge.create_semantic_symbol(invalid_statement)
    
    def test_create_semantic_symbol_with_whitespace(self):
        """Test creating symbols with whitespace handling."""
        test_input = "  All cats are animals  "
        symbol = self.bridge.create_semantic_symbol(test_input)
        
        assert symbol is not None
        assert symbol.value == test_input.strip()
    
    def test_extract_logical_components(self):
        """Test extraction of logical components."""
        # Test with a clear logical statement
        symbol = self.bridge.create_semantic_symbol("All cats are animals")
        components = self.bridge.extract_logical_components(symbol)
        
        assert isinstance(components, LogicalComponents)
        assert isinstance(components.quantifiers, list)
        assert isinstance(components.predicates, list)
        assert isinstance(components.entities, list)
        assert isinstance(components.logical_connectives, list)
        assert 0.0 <= components.confidence <= 1.0
        assert components.raw_text == "All cats are animals"
        
        # Check that some logical elements were found
        assert len(components.quantifiers) > 0 or len(components.predicates) > 0
    
    def test_extract_logical_components_complex_statement(self):
        """Test extraction with complex logical statements."""
        complex_statements = [
            "All birds can fly and some birds are colorful",
            "If all students study hard, then they will succeed",
            "There exists a cat that is both black and friendly"
        ]
        
        for statement in complex_statements:
            symbol = self.bridge.create_semantic_symbol(statement)
            components = self.bridge.extract_logical_components(symbol)
            
            assert isinstance(components, LogicalComponents)
            assert components.confidence > 0.0
            # Complex statements should have multiple logical elements
            total_elements = (
                len(components.quantifiers) + 
                len(components.predicates) + 
                len(components.entities) + 
                len(components.logical_connectives)
            )
            assert total_elements > 0
    
    def test_fallback_extraction(self):
        """Test fallback extraction functionality."""
        # Test the fallback method directly
        text = "All cats are animals and some dogs can run"
        quantifiers, predicates, entities, connectives = self.bridge._fallback_extraction(text)
        
        assert isinstance(quantifiers, list)
        assert isinstance(predicates, list)
        assert isinstance(entities, list)
        assert isinstance(connectives, list)
        
        # Should find at least some elements
        assert len(quantifiers) > 0  # "All", "some"
        assert len(predicates) > 0   # "are", "can"
        assert len(connectives) > 0  # "and"
    
    def test_parse_comma_list(self):
        """Test parsing of comma-separated lists."""
        # Test normal case
        result = self.bridge._parse_comma_list("all, every, some")
        assert result == ["all", "every", "some"]
        
        # Test with whitespace
        result = self.bridge._parse_comma_list("  all  ,  every  ,  some  ")
        assert result == ["all", "every", "some"]
        
        # Test empty/none cases
        result = self.bridge._parse_comma_list("none")
        assert result == []
        
        result = self.bridge._parse_comma_list("")
        assert result == []
        
        result = self.bridge._parse_comma_list("no")
        assert result == []
    
    def test_semantic_to_fol_basic(self):
        """Test basic semantic to FOL conversion."""
        for statement in self.test_statements:
            symbol = self.bridge.create_semantic_symbol(statement)
            result = self.bridge.semantic_to_fol(symbol)
            
            assert isinstance(result, FOLConversionResult)
            assert isinstance(result.fol_formula, str)
            assert len(result.fol_formula) > 0
            assert isinstance(result.components, LogicalComponents)
            assert 0.0 <= result.confidence <= 1.0
            assert isinstance(result.reasoning_steps, list)
            assert isinstance(result.fallback_used, bool)
            assert isinstance(result.errors, list)
    
    def test_semantic_to_fol_caching(self):
        """Test caching functionality."""
        statement = "All cats are animals"
        symbol = self.bridge.create_semantic_symbol(statement)
        
        # Clear cache first
        self.bridge.clear_cache()
        assert len(self.bridge._cache) == 0
        
        # First conversion
        result1 = self.bridge.semantic_to_fol(symbol)
        assert len(self.bridge._cache) == 1
        
        # Second conversion should use cache
        result2 = self.bridge.semantic_to_fol(symbol)
        assert result1.fol_formula == result2.fol_formula
        assert len(self.bridge._cache) == 1
    
    def test_semantic_to_fol_different_formats(self):
        """Test FOL conversion with different output formats."""
        statement = "All cats are animals"
        symbol = self.bridge.create_semantic_symbol(statement)
        
        formats = ["symbolic", "prolog", "tptp"]
        
        for fmt in formats:
            result = self.bridge.semantic_to_fol(symbol, fmt)
            assert isinstance(result, FOLConversionResult)
            assert len(result.fol_formula) > 0
            
            # Check format-specific elements
            if fmt == "prolog":
                # Prolog format should have :- or similar
                assert any(x in result.fol_formula for x in [":-", "forall", "exists"])
            elif fmt == "tptp":
                # TPTP format should have fof declaration
                assert "fof(" in result.fol_formula
    
    def test_pattern_matching(self):
        """Test pattern matching for different logical structures."""
        test_patterns = [
            ("All cats are animals", "universal quantification"),
            ("Some birds can fly", "existential quantification"),
            ("Fluffy is a cat", "simple predication"),
            ("Birds can fly", "ability predicate")
        ]
        
        for statement, expected_pattern in test_patterns:
            symbol = self.bridge.create_semantic_symbol(statement)
            components = self.bridge.extract_logical_components(symbol)
            result = self.bridge.semantic_to_fol(symbol)
            
            # Check that reasoning steps mention the expected pattern
            reasoning_text = " ".join(result.reasoning_steps).lower()
            assert any(word in reasoning_text for word in expected_pattern.split())
    
    def test_validate_fol_formula(self):
        """Test FOL formula validation."""
        # Test valid formulas
        valid_formulas = [
            "∀x (Cat(x) → Animal(x))",
            "∃x (Bird(x) ∧ CanFly(x))",
            "Animal(Fluffy)",
            "Rain → WetGround"
        ]
        
        for formula in valid_formulas:
            result = self.bridge.validate_fol_formula(formula)
            assert isinstance(result, dict)
            assert "valid" in result
            assert "errors" in result
            assert "warnings" in result
            assert "structure" in result
            
            # Valid formulas should have minimal errors
            if result["valid"]:
                assert len(result["errors"]) == 0
    
    def test_validate_fol_formula_invalid(self):
        """Test validation with invalid formulas."""
        invalid_formulas = [
            "",
            "(((",
            "∀x Cat(x → Animal(x",  # Unbalanced parentheses
            "∀X (cat(x) → animal(x))"  # Invalid variable naming
        ]
        
        for formula in invalid_formulas:
            result = self.bridge.validate_fol_formula(formula)
            assert isinstance(result, dict)
            assert "valid" in result
            
            if not result["valid"]:
                assert len(result["errors"]) > 0
    
    def test_statistics(self):
        """Test statistics gathering."""
        stats = self.bridge.get_statistics()
        
        assert isinstance(stats, dict)
        assert "symbolic_ai_available" in stats
        assert "fallback_available" in stats
        assert "cache_size" in stats
        assert "confidence_threshold" in stats
        assert "total_conversions" in stats
        
        assert stats["symbolic_ai_available"] == SYMBOLIC_AI_AVAILABLE
        assert stats["confidence_threshold"] == self.bridge.confidence_threshold
    
    def test_cache_management(self):
        """Test cache management functionality."""
        # Add some conversions to cache
        statements = ["All cats are animals", "Some birds fly"]
        for statement in statements:
            symbol = self.bridge.create_semantic_symbol(statement)
            self.bridge.semantic_to_fol(symbol)
        
        # Check cache has items
        assert len(self.bridge._cache) > 0
        
        # Clear cache
        self.bridge.clear_cache()
        assert len(self.bridge._cache) == 0
    
    def test_error_handling(self):
        """Test error handling in various scenarios."""
        # Test with problematic input that might cause errors
        problematic_inputs = [
            "This is a very complex statement with no clear logical structure whatsoever",
            "Random symbols: @#$%^&*()",
            "Numbers and dates: 123 456 2023-01-01"
        ]
        
        for problematic_input in problematic_inputs:
            try:
                symbol = self.bridge.create_semantic_symbol(problematic_input)
                result = self.bridge.semantic_to_fol(symbol)
                
                # Should still produce some result
                assert isinstance(result, FOLConversionResult)
                # But might have low confidence or errors
                assert result.confidence >= 0.0
                
            except Exception as e:
                # If it fails, it should fail gracefully
                assert isinstance(e, (ValueError, RuntimeError))
    
    def test_fallback_conversion(self):
        """Test fallback conversion when SymbolicAI is not available."""
        # Test the fallback method directly
        result = self.bridge._fallback_conversion("All cats are animals", "symbolic")
        
        assert isinstance(result, FOLConversionResult)
        assert result.fallback_used is True
        assert len(result.fol_formula) > 0
        assert result.confidence > 0.0
    
    @pytest.mark.parametrize("confidence_threshold", [0.5, 0.7, 0.9])
    def test_confidence_thresholds(self, confidence_threshold):
        """Test behavior with different confidence thresholds."""
        bridge = SymbolicFOLBridge(confidence_threshold=confidence_threshold)
        
        symbol = bridge.create_semantic_symbol("All cats are animals")
        result = bridge.semantic_to_fol(symbol)
        
        assert isinstance(result, FOLConversionResult)
        # The actual confidence may vary, but result should be consistent
        assert result.confidence >= 0.0
    
    @pytest.mark.parametrize("enable_caching", [True, False])
    def test_caching_options(self, enable_caching):
        """Test behavior with caching enabled/disabled."""
        bridge = SymbolicFOLBridge(enable_caching=enable_caching)
        
        statement = "All cats are animals"
        symbol = bridge.create_semantic_symbol(statement)
        
        # First conversion
        result1 = bridge.semantic_to_fol(symbol)
        cache_size_after_first = len(bridge._cache)
        
        # Second conversion
        result2 = bridge.semantic_to_fol(symbol)
        cache_size_after_second = len(bridge._cache)
        
        if enable_caching:
            assert cache_size_after_first > 0
            assert cache_size_after_second == cache_size_after_first
            assert result1.fol_formula == result2.fol_formula
        else:
            assert cache_size_after_first == 0
            assert cache_size_after_second == 0
    
    def test_integration_with_mock_symbolic_ai(self):
        """Test integration with mocked SymbolicAI functionality."""
        # Create a mock symbol with query method
        mock_symbol = Mock()
        mock_symbol.value = "All cats are animals"
        mock_symbol.query = Mock(side_effect=[
            "all, every",  # quantifiers
            "are, is",     # predicates  
            "cats, animals",  # entities
            "none"         # connectives
        ])
        
        # Test component extraction with mock
        components = self.bridge.extract_logical_components(mock_symbol)
        
        assert isinstance(components, LogicalComponents)
        assert "all" in components.quantifiers or "every" in components.quantifiers
        assert len(components.predicates) > 0
        assert len(components.entities) > 0


class TestLogicalComponents:
    """Test suite for LogicalComponents dataclass."""
    
    def test_logical_components_creation(self):
        """Test creation of LogicalComponents."""
        components = LogicalComponents(
            quantifiers=["all", "some"],
            predicates=["is", "can"],
            entities=["cat", "bird"],
            logical_connectives=["and", "or"],
            confidence=0.85,
            raw_text="All cats are animals and some birds can fly"
        )
        
        assert components.quantifiers == ["all", "some"]
        assert components.predicates == ["is", "can"]
        assert components.entities == ["cat", "bird"]
        assert components.logical_connectives == ["and", "or"]
        assert components.confidence == 0.85
        assert "cats" in components.raw_text


class TestFOLConversionResult:
    """Test suite for FOLConversionResult dataclass."""
    
    def test_fol_conversion_result_creation(self):
        """Test creation of FOLConversionResult."""
        components = LogicalComponents(
            quantifiers=["all"],
            predicates=["is"],
            entities=["cat", "animal"],
            logical_connectives=[],
            confidence=0.8,
            raw_text="All cats are animals"
        )
        
        result = FOLConversionResult(
            fol_formula="∀x (Cat(x) → Animal(x))",
            components=components,
            confidence=0.8,
            reasoning_steps=["Step 1", "Step 2"],
            fallback_used=False
        )
        
        assert result.fol_formula == "∀x (Cat(x) → Animal(x))"
        assert result.components == components
        assert result.confidence == 0.8
        assert result.reasoning_steps == ["Step 1", "Step 2"]
        assert result.fallback_used is False
        assert result.errors == []  # Should initialize empty
    
    def test_fol_conversion_result_with_errors(self):
        """Test FOLConversionResult with errors."""
        components = LogicalComponents([], [], [], [], 0.0, "test")
        
        result = FOLConversionResult(
            fol_formula="",
            components=components,
            confidence=0.0,
            reasoning_steps=[],
            fallback_used=True,
            errors=["Test error"]
        )
        
        assert result.errors == ["Test error"]
        assert result.fallback_used is True


# Integration tests
class TestSymbolicFOLBridgeIntegration:
    """Integration tests for SymbolicFOLBridge with other components."""
    
    def setup_method(self):
        """Setup integration test environment."""
        self.bridge = SymbolicFOLBridge()
    
    def test_end_to_end_conversion_workflow(self):
        """Test complete end-to-end conversion workflow."""
        test_cases = [
            {
                "input": "All cats are animals",
                "expected_elements": ["∀", "Cat", "Animal"],
            },
            {
                "input": "Some birds can fly",
                "expected_elements": ["∃", "Bird", "Fly"],
            },
            {
                "input": "If it rains, then the ground is wet",
                "expected_elements": ["→", "Rain", "Wet"],
            }
        ]
        
        for test_case in test_cases:
            # Step 1: Create semantic symbol
            symbol = self.bridge.create_semantic_symbol(test_case["input"])
            assert symbol is not None
            
            # Step 2: Extract components
            components = self.bridge.extract_logical_components(symbol)
            assert isinstance(components, LogicalComponents)
            
            # Step 3: Convert to FOL
            result = self.bridge.semantic_to_fol(symbol)
            assert isinstance(result, FOLConversionResult)
            assert len(result.fol_formula) > 0
            
            # Step 4: Validate formula
            validation = self.bridge.validate_fol_formula(result.fol_formula)
            assert isinstance(validation, dict)
            
            # Step 5: Check that at least some expected elements are present
            formula = result.fol_formula
            found_elements = sum(1 for elem in test_case["expected_elements"] 
                               if elem.lower() in formula.lower())
            assert found_elements > 0  # At least some elements should be found
    
    def test_batch_processing(self):
        """Test processing multiple statements in batch."""
        statements = [
            "All cats are animals",
            "Some birds can fly",
            "Fluffy is a cat",
            "If it rains, then the ground is wet"
        ]
        
        results = []
        for statement in statements:
            symbol = self.bridge.create_semantic_symbol(statement)
            result = self.bridge.semantic_to_fol(symbol)
            results.append(result)
        
        # All conversions should succeed
        assert len(results) == len(statements)
        for result in results:
            assert isinstance(result, FOLConversionResult)
            assert len(result.fol_formula) > 0
            assert result.confidence > 0.0
        
        # Check cache was populated
        if self.bridge.enable_caching:
            assert len(self.bridge._cache) == len(statements)


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
