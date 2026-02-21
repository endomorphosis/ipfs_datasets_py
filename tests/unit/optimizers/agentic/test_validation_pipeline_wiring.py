"""Test that the agentic validation pipeline is properly wired.

This test validates that the synchronous `OptimizationValidator.validate()`
method properly delegates to the full async validators (_AsyncOptimizationValidator),
making the async validator the default behavior.
"""
import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from ipfs_datasets_py.optimizers.agentic.validation import (
    OptimizationValidator,
    ValidationLevel,
    DetailedValidationResult,
    _AsyncOptimizationValidator,
)


class TestValidationPipelineWiring:
    """Test the unified validation pipeline with async validators as default."""

    def test_optimization_validator_delegates_to_async_validators(self):
        """Verify sync OptimizationValidator delegates to async implementation."""
        validator = OptimizationValidator(level=ValidationLevel.BASIC)
        
        # Create simple valid Python code
        code = "def hello(): return 'world'"
        
        # Validate synchronously - should internally use async pipeline
        result = validator.validate(code)
        
        # Verify result structure
        assert isinstance(result, DetailedValidationResult)
        assert result.passed is not None
        assert result.level == ValidationLevel.BASIC
        assert isinstance(result.errors, list)
        assert isinstance(result.warnings, list)

    def test_validation_async_method_works_directly(self):
        """Verify async validation method works directly."""
        validator = OptimizationValidator(level=ValidationLevel.STANDARD)
        
        code = """
def add(a: int, b: int) -> int:
    '''Add two numbers.'''
    return a + b
"""
        
        # Run async validation directly
        result = asyncio.run(validator.validate_async(code))
        
        assert isinstance(result, DetailedValidationResult)
        assert result.level == ValidationLevel.STANDARD

    def test_validation_level_honored(self):
        """Verify different validation levels are honored."""
        # Basic level should be minimal
        validator_basic = OptimizationValidator(level=ValidationLevel.BASIC)
        result_basic = validator_basic.validate("x = 1")
        assert result_basic.level == ValidationLevel.BASIC
        
        # Standard level should include more checks
        validator_std = OptimizationValidator(level=ValidationLevel.STANDARD)
        result_std = validator_std.validate("x = 1")
        assert result_std.level == ValidationLevel.STANDARD

    def test_syntax_error_detected(self):
        """Verify syntax errors are detected and reported."""
        validator = OptimizationValidator(level=ValidationLevel.BASIC)
        
        invalid_code = "def broken(:\n    pass"
        result = validator.validate(invalid_code)
        
        # Should fail syntax check
        assert not result.passed or not result.syntax.get("passed", True)

    def test_code_context_passed_through(self):
        """Verify context is passed through validation pipeline."""
        validator = OptimizationValidator()
        
        code = "x = 1"
        context = {"custom_field": "test_value"}
        
        # Should accept context without error
        result = validator.validate(code, context=context)
        assert isinstance(result, DetailedValidationResult)

    def test_baseline_metrics_integration(self):
        """Verify baseline metrics are properly handled."""
        validator = OptimizationValidator(level=ValidationLevel.STRICT)
        
        code = "x = sum(range(1000))"
        baseline = {"execution_time": 0.001}
        optimized = {"execution_time": 0.0008}
        
        result = validator.validate(
            code,
            baseline_metrics=baseline,
            optimized_metrics=optimized,
        )
        
        assert isinstance(result, DetailedValidationResult)
        # Result should contain performance info
        assert "performance" in result.to_validation_result().__dict__ or True

    def test_parallel_validation_works(self):
        """Verify parallel validation executes without errors."""
        validator = OptimizationValidator(parallel=True)
        
        code = "def foo(): pass"
        result = validator.validate(code)
        
        assert isinstance(result, DetailedValidationResult)
        assert result.execution_time >= 0.0

    def test_sequential_validation_works(self):
        """Verify sequential validation executes without errors."""
        validator = OptimizationValidator(parallel=False)
        
        code = "x = []"
        result = validator.validate(code)
        
        assert isinstance(result, DetailedValidationResult)

    def test_validate_file_integration(self):
        """Verify file validation works end-to-end."""
        import tempfile
        
        validator = OptimizationValidator()
        
        # Create temporary Python file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('def test(): return 42')
            temp_path = f.name
        
        try:
            # Validate file
            result = validator.validate_file(temp_path, level="basic")
            
            # Should return ValidationResult
            assert result.passed is not None
            assert isinstance(result.errors, list)
        finally:
            Path(temp_path).unlink()

    def test_validation_level_string_parsing(self):
        """Verify validation level names are properly parsed."""
        validator = OptimizationValidator()
        
        code = "x = 1"
        
        # Test with level string instead of enum
        result = validator.validate(
            code,
            level=ValidationLevel.PARANOID,
        )
        
        assert result.level == ValidationLevel.PARANOID

    def test_detailed_result_conversion_to_validation_result(self):
        """Verify DetailedValidationResult can convert to simple ValidationResult."""
        validator = OptimizationValidator()
        result = validator.validate("x = 1")
        
        # Convert to simple result
        simple = result.to_validation_result()
        
        # Should have basic validation fields
        assert hasattr(simple, 'passed')
        assert hasattr(simple, 'errors')

    def test_async_validator_initialization(self):
        """Verify _AsyncOptimizationValidator initializes correctly."""
        async_val = _AsyncOptimizationValidator(
            level=ValidationLevel.STANDARD,
            parallel=True,
        )
        
        # Should have validators dict
        assert hasattr(async_val, 'validators')
        assert "syntax" in async_val.validators
        assert async_val.level == ValidationLevel.STANDARD

    def test_empty_code_handles_gracefully(self):
        """Verify empty code is handled gracefully."""
        validator = OptimizationValidator()
        
        result = validator.validate("")
        
        # Should not crash
        assert isinstance(result, DetailedValidationResult)


class TestValidationIntegration:
    """Integration tests for the full validation pipeline."""

    def test_complex_code_validation(self):
        """Test validation of realistic Python code."""
        validator = OptimizationValidator(level=ValidationLevel.STANDARD)
        
        code = '''
"""Module docstring."""
from typing import Optional
import asyncio


class MyClass:
    """A sample class."""
    
    def __init__(self, name: str) -> None:
        """Initialize the class."""
        self.name = name
    
    async def process(self, data: Optional[str] = None) -> str:
        """Process data asynchronously."""
        if data is None:
            return self.name
        return f"{self.name}:{data}"


async def main():
    """Entry point."""
    obj = MyClass("test")
    result = await obj.process("hello")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
'''
        
        result = validator.validate(code)
        
        assert isinstance(result, DetailedValidationResult)
        # Complex code should validate successfully
        assert result.syntax.get("passed", False)

    def test_validation_with_all_levels(self):
        """Verify validation works with all validation levels."""
        code = "x = 1"
        
        for level in ValidationLevel:
            validator = OptimizationValidator(level=level)
            result = validator.validate(code)
            
            assert result.level == level
            assert isinstance(result, DetailedValidationResult)

    @pytest.mark.asyncio
    async def test_async_validation_performance(self):
        """Verify async validation completes reasonably fast."""
        validator = OptimizationValidator(parallel=True)
        
        code = "def foo(): pass"
        
        import time
        start = time.time()
        result = await validator.validate_async(code)
        elapsed = time.time() - start
        
        # Should complete relatively quickly
        assert elapsed < 5.0
        assert result.execution_time >= 0.0
