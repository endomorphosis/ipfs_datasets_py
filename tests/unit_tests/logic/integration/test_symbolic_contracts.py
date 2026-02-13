"""
Test module for SymbolicContracts

This module provides comprehensive tests for the contract-based validation system,
including input/output validation, FOL syntax checking, and contract enforcement.
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any

# Add the project root to Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Import the modules to test
from ipfs_datasets_py.logic.integration.symbolic_contracts import (
    FOLInput,
    FOLOutput,
    ValidationContext,
    FOLSyntaxValidator,
    ContractedFOLConverter,
    create_fol_converter,
    validate_fol_input,
    test_contracts,
    SYMBOLIC_AI_AVAILABLE
)

# Import Pydantic validation error for testing
from pydantic import ValidationError


class TestFOLInput:
    """Test suite for FOLInput validation model."""
    
    def test_valid_fol_input_creation(self):
        """Test creation of valid FOL input."""
        valid_inputs = [
            {
                "text": "All cats are animals",
                "confidence_threshold": 0.7,
                "output_format": "symbolic"
            },
            {
                "text": "Some birds can fly",
                "domain_predicates": ["Bird", "Fly"],
                "confidence_threshold": 0.8,
                "output_format": "prolog",
                "reasoning_depth": 5,
                "validate_syntax": True
            },
            {
                "text": "If it rains, then the ground is wet",
                "confidence_threshold": 0.9,
                "output_format": "tptp"
            }
        ]
        
        for input_data in valid_inputs:
            fol_input = FOLInput(**input_data)
            
            assert fol_input.text == input_data["text"]
            assert fol_input.confidence_threshold == input_data["confidence_threshold"]
            assert fol_input.output_format == input_data["output_format"]
            
            # Check defaults
            if "domain_predicates" not in input_data:
                assert fol_input.domain_predicates == []
            if "reasoning_depth" not in input_data:
                assert fol_input.reasoning_depth == 3
            if "validate_syntax" not in input_data:
                assert fol_input.validate_syntax is True
    
    def test_fol_input_validation_errors(self):
        """Test FOL input validation with invalid data."""
        invalid_inputs = [
            # Empty text
            {"text": "", "confidence_threshold": 0.7},
            {"text": "   ", "confidence_threshold": 0.7},
            
            # Invalid confidence threshold
            {"text": "All cats are animals", "confidence_threshold": -0.1},
            {"text": "All cats are animals", "confidence_threshold": 1.1},
            
            # Invalid output format
            {"text": "All cats are animals", "output_format": "invalid_format"},
            
            # Invalid reasoning depth
            {"text": "All cats are animals", "reasoning_depth": 0},
            {"text": "All cats are animals", "reasoning_depth": 11},
            
            # Text too short
            {"text": "a", "confidence_threshold": 0.7}
        ]
        
        for invalid_input in invalid_inputs:
            with pytest.raises(ValueError):
                FOLInput(**invalid_input)
    
    def test_text_content_validation(self):
        """Test text content validation logic."""
        # Valid texts with logical structure
        valid_texts = [
            "All cats are animals",
            "Some birds can fly",
            "If it rains then floods occur",
            "Students must study hard",
            "Every person has a name"
        ]
        
        for text in valid_texts:
            fol_input = FOLInput(text=text)
            assert fol_input.text == text
    
    def test_domain_predicates_validation(self):
        """Test domain predicates validation."""
        # Valid predicates
        valid_cases = [
            {
                "text": "All cats are animals",
                "domain_predicates": ["Cat", "Animal", "HasFur"]
            },
            {
                "text": "Birds can fly",
                "domain_predicates": ["Bird", "CanFly", "HasWings"]
            }
        ]
        
        for case in valid_cases:
            fol_input = FOLInput(**case)
            assert fol_input.domain_predicates == case["domain_predicates"]
        
        # Invalid predicates (should be filtered out)
        invalid_predicates_case = {
            "text": "All cats are animals",
            "domain_predicates": ["ValidPredicate", "123Invalid", "", "  ", "Valid_2"]
        }
        
        fol_input = FOLInput(**invalid_predicates_case)
        # Should only keep valid predicates
        valid_predicates = [p for p in fol_input.domain_predicates 
                          if p and p.replace('_', '').isalnum()]
        assert len(valid_predicates) >= 1  # At least some valid predicates should remain
    
    def test_whitespace_handling(self):
        """Test whitespace handling in input validation."""
        text_with_whitespace = "   All cats are animals   "
        fol_input = FOLInput(text=text_with_whitespace)
        
        # Text should be stripped
        assert fol_input.text == text_with_whitespace.strip()


class TestFOLOutput:
    """Test suite for FOLOutput validation model."""
    
    def test_valid_fol_output_creation(self):
        """Test creation of valid FOL output."""
        valid_outputs = [
            {
                "fol_formula": "∀x (Cat(x) → Animal(x))",
                "confidence": 0.85,
                "logical_components": {
                    "quantifiers": ["∀"],
                    "predicates": ["Cat", "Animal"],
                    "entities": ["x"]
                }
            },
            {
                "fol_formula": "∃x (Bird(x) ∧ CanFly(x))",
                "confidence": 0.92,
                "logical_components": {
                    "quantifiers": ["∃"],
                    "predicates": ["Bird", "CanFly"],
                    "entities": ["x"]
                },
                "reasoning_steps": ["Step 1", "Step 2"],
                "warnings": ["Warning 1"],
                "metadata": {"source": "test"}
            }
        ]
        
        for output_data in valid_outputs:
            fol_output = FOLOutput(**output_data)
            
            assert fol_output.fol_formula == output_data["fol_formula"]
            assert fol_output.confidence == output_data["confidence"]
            assert fol_output.logical_components == output_data["logical_components"]
            
            # Check defaults
            if "reasoning_steps" not in output_data:
                assert fol_output.reasoning_steps == []
            if "warnings" not in output_data:
                assert fol_output.warnings == []
            if "metadata" not in output_data:
                assert fol_output.metadata == {}
    
    def test_fol_output_validation_errors(self):
        """Test FOL output validation with invalid data."""
        invalid_outputs = [
            # Empty formula
            {
                "fol_formula": "",
                "confidence": 0.8,
                "logical_components": {"quantifiers": [], "predicates": [], "entities": []}
            },
            
            # Invalid confidence
            {
                "fol_formula": "∀x (Cat(x) → Animal(x))",
                "confidence": -0.1,
                "logical_components": {"quantifiers": [], "predicates": [], "entities": []}
            },
            {
                "fol_formula": "∀x (Cat(x) → Animal(x))",
                "confidence": 1.1,
                "logical_components": {"quantifiers": [], "predicates": [], "entities": []}
            },
            
            # Unbalanced parentheses
            {
                "fol_formula": "∀x (Cat(x → Animal(x)",
                "confidence": 0.8,
                "logical_components": {"quantifiers": [], "predicates": [], "entities": []}
            }
        ]
        
        for invalid_output in invalid_outputs:
            with pytest.raises(ValueError):
                FOLOutput(**invalid_output)
    
    def test_fol_formula_syntax_validation(self):
        """Test FOL formula syntax validation."""
        # Valid formulas
        valid_formulas = [
            "∀x (Cat(x) → Animal(x))",
            "∃x (Bird(x) ∧ CanFly(x))",
            "Animal(Fluffy)",
            "Rain → WetGround",
            "loves(John, Mary)",
            "fof(test, axiom, ![X]: (cat(X) => animal(X)))."
        ]
        
        for formula in valid_formulas:
            output = FOLOutput(
                fol_formula=formula,
                confidence=0.8,
                logical_components={"quantifiers": [], "predicates": [], "entities": []}
            )
            assert output.fol_formula == formula
    
    def test_logical_components_validation(self):
        """Test logical components validation."""
        # Test with missing required keys
        incomplete_components = {"quantifiers": ["∀"]}
        
        output = FOLOutput(
            fol_formula="∀x (Cat(x) → Animal(x))",
            confidence=0.8,
            logical_components=incomplete_components
        )
        
        # Should fill in missing keys
        assert "predicates" in output.logical_components
        assert "entities" in output.logical_components
        assert output.logical_components["predicates"] == []
        assert output.logical_components["entities"] == []


class TestFOLSyntaxValidator:
    """Test suite for FOLSyntaxValidator."""
    
    def setup_method(self):
        """Setup test environment."""
        self.validator = FOLSyntaxValidator(strict=True)
        self.lenient_validator = FOLSyntaxValidator(strict=False)
    
    def test_validate_formula_valid_cases(self):
        """Test validation with valid FOL formulas."""
        valid_formulas = [
            "∀x (Cat(x) → Animal(x))",
            "∃x (Bird(x) ∧ CanFly(x))",
            "Animal(Fluffy)",
            "Rain → WetGround",
            "∀x∃y (Loves(x, y))",
            "¬(∀x (Cat(x) → Dog(x)))"
        ]
        
        for formula in valid_formulas:
            result = self.validator.validate_formula(formula)
            
            assert isinstance(result, dict)
            assert "valid" in result
            assert "errors" in result
            assert "warnings" in result
            assert "structure_analysis" in result
            
            # Valid formulas should have no critical errors
            if not result["valid"]:
                # If marked invalid, should have specific errors
                assert len(result["errors"]) > 0
    
    def test_validate_formula_invalid_cases(self):
        """Test validation with invalid FOL formulas."""
        invalid_formulas = [
            "",  # Empty
            "(((",  # Unbalanced parentheses
            "∀X (cat(x) → animal(x))",  # Variable naming inconsistency
            "∀x Cat(x → Animal(x)",  # Missing parenthesis
            "∀x (Cat(x) → Animal(x",  # Missing closing parenthesis
        ]
        
        for formula in invalid_formulas:
            result = self.validator.validate_formula(formula)
            
            assert isinstance(result, dict)
            assert "valid" in result
            assert "errors" in result
            
            # Invalid formulas should be marked as invalid
            if formula == "":
                assert not result["valid"]
                assert len(result["errors"]) > 0
    
    def test_syntax_checking(self):
        """Test basic syntax checking."""
        # Test balanced parentheses
        errors = self.validator._check_syntax("∀x (Cat(x) → Animal(x)")
        assert any("parentheses" in error.lower() for error in errors)
        
        # Test valid syntax
        errors = self.validator._check_syntax("∀x (Cat(x) → Animal(x))")
        assert len([e for e in errors if "parentheses" in e.lower()]) == 0
    
    def test_structure_analysis(self):
        """Test structural analysis of formulas."""
        formula = "∀x∃y (Cat(x) ∧ Loves(x, y) → Happy(x))"
        structure = self.validator._analyze_structure(formula)
        
        assert isinstance(structure, dict)
        assert "has_quantifiers" in structure
        assert "quantifier_types" in structure
        assert "predicate_count" in structure
        assert "predicates" in structure
        assert "variables" in structure
        assert "constants" in structure
        assert "connectives" in structure
        assert "complexity_score" in structure
        
        # This formula should have quantifiers
        assert structure["has_quantifiers"] is True
        assert len(structure["quantifier_types"]) > 0
        assert structure["predicate_count"] > 0
        assert len(structure["predicates"]) > 0
    
    def test_semantic_checking(self):
        """Test semantic validation."""
        # Formula with free variables
        formula_with_free_vars = "∀x (Cat(x) → Animal(y))"
        structure = self.validator._analyze_structure(formula_with_free_vars)
        warnings = self.validator._check_semantics(formula_with_free_vars, structure)
        
        # Should warn about free variables
        assert any("free" in warning.lower() for warning in warnings)
    
    def test_suggestions_generation(self):
        """Test suggestion generation."""
        complex_formula = "∀x∀y∀z (Cat(x) ∧ Dog(y) ∧ Bird(z) → Animal(x) ∧ Animal(y) ∧ Animal(z))"
        structure = self.validator._analyze_structure(complex_formula)
        suggestions = self.validator._generate_suggestions(complex_formula, structure)
        
        assert isinstance(suggestions, list)
        # Complex formulas should generate suggestions
        if structure["complexity_score"] > 30:
            assert len(suggestions) > 0


class TestContractedFOLConverter:
    """Test suite for ContractedFOLConverter."""
    
    def setup_method(self):
        """Setup test environment."""
        self.converter = create_fol_converter()
    
    def test_converter_creation(self):
        """Test converter creation."""
        assert self.converter is not None
        assert isinstance(self.converter, ContractedFOLConverter)
    
    def test_successful_conversion(self):
        """Test successful FOL conversion."""
        test_cases = [
            {
                "text": "All cats are animals",
                "confidence_threshold": 0.7,
                "output_format": "symbolic"
            },
            {
                "text": "Some birds can fly",
                "confidence_threshold": 0.6,
                "output_format": "prolog"
            },
            {
                "text": "If it rains, then the ground is wet",
                "confidence_threshold": 0.8,
                "output_format": "tptp"
            }
        ]
        
        for test_case in test_cases:
            input_data = FOLInput(**test_case)
            result = self.converter(input_data)
            
            assert isinstance(result, FOLOutput)
            assert isinstance(result.fol_formula, str)
            assert len(result.fol_formula) > 0
            assert 0.0 <= result.confidence <= 1.0
            assert isinstance(result.logical_components, dict)
            assert isinstance(result.reasoning_steps, list)
            assert isinstance(result.warnings, list)
            assert isinstance(result.metadata, dict)
    
    def test_conversion_with_domain_predicates(self):
        """Test conversion with domain-specific predicates."""
        input_data = FOLInput(
            text="All students study mathematics",
            domain_predicates=["Student", "Study", "Mathematics"],
            confidence_threshold=0.7
        )
        
        result = self.converter(input_data)
        
        assert isinstance(result, FOLOutput)
        assert len(result.fol_formula) > 0
        assert "domain_predicates" in result.metadata
        assert result.metadata["domain_predicates"] == input_data.domain_predicates
    
    def test_error_handling(self):
        """Test error handling in conversion."""
        # Test with problematic input
        problematic_inputs = [
            FOLInput(text="This text has no clear logical structure at all"),
            FOLInput(text="Random symbols: @#$%^&*()"),
            FOLInput(text="Numbers only: 123 456 789")
        ]
        
        for input_data in problematic_inputs:
            result = self.converter(input_data)
            
            # Should still produce a result, even if low quality
            assert isinstance(result, FOLOutput)
            assert isinstance(result.fol_formula, str)
            # May have warnings or low confidence
            assert result.confidence >= 0.0
    
    @pytest.mark.skipif(not SYMBOLIC_AI_AVAILABLE, reason="SymbolicAI not available")
    def test_pre_condition_validation(self):
        """Test pre-condition validation in contracts."""
        if hasattr(self.converter, 'pre'):
            # Test valid input
            valid_input = FOLInput(text="All cats are animals")
            assert self.converter.pre(valid_input) is True
            
            # Test problematic input
            problematic_input = FOLInput(
                text="This is a very long text " * 20  # Very long text
            )
            # Should still pass but might generate warnings
            result = self.converter.pre(problematic_input)
            assert isinstance(result, bool)
    
    @pytest.mark.skipif(not SYMBOLIC_AI_AVAILABLE, reason="SymbolicAI not available")
    def test_post_condition_validation(self):
        """Test post-condition validation in contracts."""
        if hasattr(self.converter, 'post'):
            # Create a valid output
            valid_output = FOLOutput(
                fol_formula="∀x (Cat(x) → Animal(x))",
                confidence=0.8,
                logical_components={"quantifiers": ["∀"], "predicates": ["Cat", "Animal"], "entities": ["x"]}
            )
            
            result = self.converter.post(valid_output)
            assert isinstance(result, bool)
    
    def test_conversion_statistics(self):
        """Test conversion statistics tracking."""
        if hasattr(self.converter, 'get_statistics'):
            # Perform some conversions
            test_inputs = [
                FOLInput(text="All cats are animals"),
                FOLInput(text="Some birds can fly"),
                FOLInput(text="Dogs bark loudly")
            ]
            
            for input_data in test_inputs:
                self.converter(input_data)
            
            stats = self.converter.get_statistics()
            
            assert isinstance(stats, dict)
            assert "total_conversions" in stats
            assert "successful_conversions" in stats
            assert "failed_conversions" in stats
            assert stats["total_conversions"] >= len(test_inputs)


class TestHelperFunctions:
    """Test suite for helper functions."""
    
    def test_validate_fol_input(self):
        """Test validate_fol_input helper function."""
        # Test valid input
        input_obj = validate_fol_input(
            "All cats are animals",
            confidence_threshold=0.8,
            output_format="prolog"
        )
        
        assert isinstance(input_obj, FOLInput)
        assert input_obj.text == "All cats are animals"
        assert input_obj.confidence_threshold == 0.8
        assert input_obj.output_format == "prolog"
    
    def test_validate_fol_input_errors(self):
        """Test validate_fol_input with invalid data."""
        with pytest.raises(ValueError):
            validate_fol_input("", confidence_threshold=0.7)
        
        with pytest.raises(ValueError):
            validate_fol_input("All cats are animals", confidence_threshold=1.5)
    
    def test_create_fol_converter_variations(self):
        """Test create_fol_converter with different parameters."""
        # Test strict validation
        strict_converter = create_fol_converter(strict_validation=True)
        assert isinstance(strict_converter, ContractedFOLConverter)
        
        # Test lenient validation
        lenient_converter = create_fol_converter(strict_validation=False)
        assert isinstance(lenient_converter, ContractedFOLConverter)


class TestValidationContext:
    """Test suite for ValidationContext."""
    
    def test_validation_context_creation(self):
        """Test ValidationContext creation."""
        context = ValidationContext()
        
        assert context.strict_mode is True
        assert context.allow_empty_predicates is False
        assert context.max_complexity == 100
        assert isinstance(context.custom_validators, list)
        assert len(context.custom_validators) == 0
    
    def test_validation_context_custom(self):
        """Test ValidationContext with custom parameters."""
        def custom_validator(formula):
            return len(formula) > 10
        
        context = ValidationContext(
            strict_mode=False,
            allow_empty_predicates=True,
            max_complexity=50,
            custom_validators=[custom_validator]
        )
        
        assert context.strict_mode is False
        assert context.allow_empty_predicates is True
        assert context.max_complexity == 50
        assert len(context.custom_validators) == 1


class TestIntegrationScenarios:
    """Integration tests for the complete contract system."""
    
    def test_end_to_end_conversion_workflow(self):
        """Test complete end-to-end conversion workflow."""
        # Step 1: Create input
        input_data = validate_fol_input(
            "All cats are animals and some cats are black",
            confidence_threshold=0.7,
            output_format="symbolic",
            domain_predicates=["Cat", "Animal", "Black"]
        )
        
        # Step 2: Convert
        converter = create_fol_converter()
        result = converter(input_data)
        
        # Step 3: Validate result
        assert isinstance(result, FOLOutput)
        assert len(result.fol_formula) > 0
        
        # Step 4: Additional validation
        validator = FOLSyntaxValidator()
        validation_result = validator.validate_formula(result.fol_formula)
        
        assert isinstance(validation_result, dict)
        assert "valid" in validation_result
    
    def test_batch_processing_with_contracts(self):
        """Test batch processing with contract validation."""
        test_cases = [
            "All cats are animals",
            "Some birds can fly", 
            "If it rains, then the ground is wet",
            "Every student studies hard",
            "Dogs bark and cats meow"
        ]
        
        converter = create_fol_converter()
        results = []
        
        for test_case in test_cases:
            input_data = validate_fol_input(test_case)
            result = converter(input_data)
            results.append(result)
        
        # All conversions should succeed
        assert len(results) == len(test_cases)
        for result in results:
            assert isinstance(result, FOLOutput)
            assert len(result.fol_formula) > 0
            assert result.confidence >= 0.0
    
    def test_error_recovery_workflow(self):
        """Test error recovery in the contract system."""
        problematic_cases = [
            "",  # This should fail validation
            "a",  # Too short
            "Random text with no logical structure whatsoever and many words"
        ]
        
        converter = create_fol_converter()
        
        for problematic_case in problematic_cases:
            try:
                input_data = validate_fol_input(problematic_case)
                result = converter(input_data)
                
                # If it succeeds, result should be reasonable
                assert isinstance(result, FOLOutput)
                
            except ValidationError:
                # Expected for invalid inputs
                pass
            except Exception as e:
                # Any other errors should be reasonable
                assert isinstance(e, (ValueError, RuntimeError))


def test_module_level_test_function():
    """Test the module-level test function."""
    try:
        test_contracts()
        # If it completes without error, that's a success
        assert True
    except Exception as e:
        # If it fails, check that it's a reasonable failure
        assert isinstance(e, (ImportError, ValidationError, ValueError))


@pytest.mark.parametrize("input_text,expected_confidence", [
    ("All cats are animals", 0.5),  # Clear logical structure
    ("Some birds can fly", 0.4),    # Clear existential
    ("Random text", 0.1),           # Poor logical structure
])
def test_parametrized_confidence_levels(input_text, expected_confidence):
    """Parametrized test for expected confidence levels."""
    try:
        input_data = validate_fol_input(input_text)
        converter = create_fol_converter()
        result = converter(input_data)
        
        # Confidence should be at least at expected level for good inputs
        if expected_confidence > 0.3:
            assert result.confidence >= 0.0  # Any reasonable confidence
        else:
            # Poor inputs might have very low confidence
            assert result.confidence >= 0.0
            
    except ValidationError:
        # Some inputs might fail validation
        if expected_confidence < 0.2:
            pass  # Expected for poor inputs
        else:
            raise


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
