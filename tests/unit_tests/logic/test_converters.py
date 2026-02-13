"""
Tests for logic/common/converters.py

These tests validate the base converter classes and common patterns.
"""

import pytest
from typing import Dict, Any

from ipfs_datasets_py.logic.common import (
    LogicConverter,
    ChainedConverter,
    ConversionResult,
    ConversionStatus,
    ValidationResult,
    ConversionError
)


class SimpleConverter(LogicConverter[str, str]):
    """A simple test converter that uppercases strings."""
    
    def validate_input(self, input_data: str) -> ValidationResult:
        result = ValidationResult(valid=True)
        if not input_data:
            result.add_error("Input cannot be empty")
        if len(input_data) > 100:
            result.add_warning("Input is very long")
        return result
    
    def _convert_impl(self, input_data: str, options: Dict[str, Any]) -> str:
        return input_data.upper()


class ReverseConverter(LogicConverter[str, str]):
    """A test converter that reverses strings."""
    
    def validate_input(self, input_data: str) -> ValidationResult:
        return ValidationResult(valid=True)
    
    def _convert_impl(self, input_data: str, options: Dict[str, Any]) -> str:
        return input_data[::-1]


class FailingConverter(LogicConverter[str, str]):
    """A test converter that always fails."""
    
    def validate_input(self, input_data: str) -> ValidationResult:
        return ValidationResult(valid=True)
    
    def _convert_impl(self, input_data: str, options: Dict[str, Any]) -> str:
        raise ConversionError("Conversion always fails", context={"input": input_data})


class TestConversionResult:
    """Test ConversionResult dataclass."""
    
    def test_success_property_with_success_status(self):
        """GIVEN a ConversionResult with SUCCESS status
        WHEN checking success property
        THEN it returns True
        """
        result = ConversionResult(status=ConversionStatus.SUCCESS)
        assert result.success is True
    
    def test_success_property_with_partial_status(self):
        """GIVEN a ConversionResult with PARTIAL status
        WHEN checking success property
        THEN it returns True
        """
        result = ConversionResult(status=ConversionStatus.PARTIAL)
        assert result.success is True
    
    def test_success_property_with_failed_status(self):
        """GIVEN a ConversionResult with FAILED status
        WHEN checking success property
        THEN it returns False
        """
        result = ConversionResult(status=ConversionStatus.FAILED)
        assert result.success is False
    
    def test_add_error_sets_failed_status(self):
        """GIVEN a ConversionResult
        WHEN adding an error
        THEN status is set to FAILED
        """
        result = ConversionResult(status=ConversionStatus.SUCCESS)
        result.add_error("Test error")
        
        assert result.status == ConversionStatus.FAILED
        assert "Test error" in result.errors
    
    def test_add_warning_sets_partial_status(self):
        """GIVEN a ConversionResult with SUCCESS status
        WHEN adding a warning
        THEN status is set to PARTIAL
        """
        result = ConversionResult(status=ConversionStatus.SUCCESS)
        result.add_warning("Test warning")
        
        assert result.status == ConversionStatus.PARTIAL
        assert "Test warning" in result.warnings
    
    def test_to_dict_includes_all_fields(self):
        """GIVEN a ConversionResult with data
        WHEN converting to dict
        THEN all fields are included
        """
        result = ConversionResult(
            output="test output",
            status=ConversionStatus.SUCCESS,
            confidence=0.95,
            errors=["error1"],
            warnings=["warning1"]
        )
        
        dict_repr = result.to_dict()
        assert dict_repr["output"] == "test output"
        assert dict_repr["status"] == "success"
        assert dict_repr["confidence"] == 0.95
        assert dict_repr["success"] is True
        assert dict_repr["errors"] == ["error1"]
        assert dict_repr["warnings"] == ["warning1"]


class TestValidationResult:
    """Test ValidationResult dataclass."""
    
    def test_add_error_sets_invalid(self):
        """GIVEN a ValidationResult that is valid
        WHEN adding an error
        THEN valid becomes False
        """
        result = ValidationResult(valid=True)
        result.add_error("Test error")
        
        assert result.valid is False
        assert "Test error" in result.errors
    
    def test_add_warning_keeps_valid(self):
        """GIVEN a ValidationResult that is valid
        WHEN adding a warning
        THEN it remains valid
        """
        result = ValidationResult(valid=True)
        result.add_warning("Test warning")
        
        assert result.valid is True
        assert "Test warning" in result.warnings


class TestLogicConverter:
    """Test LogicConverter base class."""
    
    def test_successful_conversion(self):
        """GIVEN a simple converter and valid input
        WHEN converting
        THEN output is correct with SUCCESS status
        """
        converter = SimpleConverter()
        result = converter.convert("hello")
        
        assert result.success is True
        assert result.output == "HELLO"
        assert result.status == ConversionStatus.SUCCESS
        assert len(result.errors) == 0
    
    def test_conversion_with_validation_error(self):
        """GIVEN a converter and invalid input
        WHEN converting
        THEN conversion fails with validation errors
        """
        converter = SimpleConverter()
        result = converter.convert("")  # Empty string
        
        assert result.success is False
        assert result.status == ConversionStatus.FAILED
        assert "Input cannot be empty" in result.errors
    
    def test_conversion_with_warning(self):
        """GIVEN a converter and input that triggers warnings
        WHEN converting
        THEN conversion succeeds with PARTIAL status
        """
        converter = SimpleConverter()
        long_input = "x" * 101  # Triggers warning
        result = converter.convert(long_input)
        
        assert result.success is True
        assert result.status == ConversionStatus.PARTIAL
        assert len(result.warnings) > 0
        assert "very long" in result.warnings[0]
    
    def test_caching_enabled(self):
        """GIVEN a converter with caching enabled
        WHEN converting the same input twice
        THEN second result is from cache
        """
        converter = SimpleConverter(enable_caching=True)
        
        # First conversion
        result1 = converter.convert("hello")
        assert result1.status == ConversionStatus.SUCCESS
        
        # Second conversion (should be cached)
        result2 = converter.convert("hello")
        assert result2.status == ConversionStatus.CACHED
        assert result2.output == result1.output
    
    def test_caching_disabled(self):
        """GIVEN a converter with caching disabled
        WHEN converting the same input twice
        THEN both conversions execute fully
        """
        converter = SimpleConverter(enable_caching=False)
        
        result1 = converter.convert("hello")
        result2 = converter.convert("hello")
        
        assert result1.status == ConversionStatus.SUCCESS
        assert result2.status == ConversionStatus.SUCCESS
        assert result2.status != ConversionStatus.CACHED
    
    def test_validation_disabled(self):
        """GIVEN a converter with validation disabled
        WHEN converting invalid input
        THEN validation is skipped and conversion proceeds
        """
        converter = SimpleConverter(enable_validation=False)
        result = converter.convert("")  # Empty string, normally invalid
        
        # Without validation, convert_impl is called which will succeed or fail
        # based on its own logic
        assert result is not None
    
    def test_clear_cache(self):
        """GIVEN a converter with cached results
        WHEN clearing the cache
        THEN subsequent conversions are not cached
        """
        converter = SimpleConverter(enable_caching=True)
        
        # Cache a result
        result1 = converter.convert("hello")
        assert result1.status == ConversionStatus.SUCCESS
        
        # Clear cache
        converter.clear_cache()
        
        # Convert again
        result2 = converter.convert("hello")
        assert result2.status == ConversionStatus.SUCCESS  # Not CACHED
    
    def test_cache_stats(self):
        """GIVEN a converter with some cached results
        WHEN getting cache stats
        THEN correct statistics are returned
        """
        converter = SimpleConverter(enable_caching=True)
        
        # Initial stats
        stats = converter.get_cache_stats()
        assert stats["cache_size"] == 0
        assert stats["cache_enabled"] is True
        
        # Add some cached results
        converter.convert("hello")
        converter.convert("world")
        
        # Check updated stats
        stats = converter.get_cache_stats()
        assert stats["cache_size"] == 2
    
    def test_conversion_error_handling(self):
        """GIVEN a converter that raises ConversionError
        WHEN converting
        THEN error is caught and result indicates failure
        """
        converter = FailingConverter()
        result = converter.convert("test")
        
        assert result.success is False
        assert result.status == ConversionStatus.FAILED
        assert len(result.errors) > 0
        assert "Conversion always fails" in result.errors[0]


class TestChainedConverter:
    """Test ChainedConverter class."""
    
    def test_two_step_chain(self):
        """GIVEN a chain of two converters
        WHEN converting
        THEN both conversions are applied in order
        """
        converter = ChainedConverter([
            SimpleConverter(),  # Uppercase
            ReverseConverter()  # Reverse
        ])
        
        result = converter.convert("hello")
        
        assert result.success is True
        assert result.output == "OLLEH"  # "hello" -> "HELLO" -> "OLLEH"
    
    def test_chain_with_empty_list(self):
        """GIVEN a chain with no converters
        WHEN converting
        THEN validation fails
        """
        converter = ChainedConverter([])
        result = converter.convert("test")
        
        assert result.success is False
        assert "No converters in chain" in result.errors
    
    def test_chain_fails_at_middle_step(self):
        """GIVEN a chain where a middle converter fails
        WHEN converting
        THEN the chain stops and reports the failure
        """
        converter = ChainedConverter([
            SimpleConverter(),
            FailingConverter(),  # This will fail
            ReverseConverter()   # This won't be reached
        ])
        
        result = converter.convert("hello")
        
        assert result.success is False
        assert "Conversion failed at step 2" in result.errors[0]
    
    def test_chain_with_single_converter(self):
        """GIVEN a chain with a single converter
        WHEN converting
        THEN it behaves like a simple converter
        """
        converter = ChainedConverter([SimpleConverter()])
        result = converter.convert("hello")
        
        assert result.success is True
        assert result.output == "HELLO"


class TestConverterOptions:
    """Test converter options and configuration."""
    
    def test_custom_confidence(self):
        """GIVEN conversion options with custom confidence
        WHEN converting
        THEN result has the specified confidence
        """
        converter = SimpleConverter()
        result = converter.convert("hello", options={"confidence": 0.75})
        
        assert result.confidence == 0.75
    
    def test_use_cache_option(self):
        """GIVEN a converter with a cached result
        WHEN converting with use_cache=False
        THEN cache is bypassed
        """
        converter = SimpleConverter(enable_caching=True)
        
        # Cache a result
        result1 = converter.convert("hello")
        assert result1.status == ConversionStatus.SUCCESS
        
        # Convert again with cache disabled
        result2 = converter.convert("hello", use_cache=False)
        assert result2.status == ConversionStatus.SUCCESS  # Not CACHED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
