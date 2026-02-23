"""Tests for exception handling utilities.

Validates format_validation_errors, wrap_exceptions, exception_to_dict, and safe_error_handler.
"""

import logging
from unittest.mock import MagicMock

import pytest

from ipfs_datasets_py.optimizers.common.exceptions import (
    ConfigurationError,
    ExtractionError,
    OptimizerError,
    ProvingError,
    ValidationError,
    exception_to_dict,
    format_validation_errors,
    safe_error_handler,
    wrap_exceptions,
)


class TestFormatValidationErrors:
    """Tests for format_validation_errors function."""
    
    def test_empty_list(self):
        """GIVEN: Empty error list
        WHEN: format_validation_errors called
        THEN: Returns 'No validation errors'
        """
        result = format_validation_errors([])
        assert result == "No validation errors"
    
    def test_single_error(self):
        """GIVEN: Single validation error
        WHEN: format_validation_errors called
        THEN: Returns formatted message with singular 'error'
        """
        errors = ["Missing field: id"]
        result = format_validation_errors(errors)
        
        assert "1 validation error:" in result
        assert "1. Missing field: id" in result
    
    def test_multiple_errors(self):
        """GIVEN: Multiple validation errors
        WHEN: format_validation_errors called
        THEN: Returns numbered list of all errors
        """
        errors = ["Missing field: id", "Invalid type: foo", "Bad value: -1"]
        result = format_validation_errors(errors)
        
        assert "3 validation errors:" in result
        assert "1. Missing field: id" in result
        assert "2. Invalid type: foo" in result
        assert "3. Bad value: -1" in result
    
    def test_truncation(self):
        """GIVEN: More errors than max_errors
        WHEN: format_validation_errors called
        THEN: Shows only first max_errors and indicates more exist
        """
        errors = [f"Error {i}" for i in range(10)]
        result = format_validation_errors(errors, max_errors=3)
        
        assert "10 validation errors:" in result
        assert "1. Error 0" in result
        assert "2. Error 1" in result
        assert "3. Error 2" in result
        assert "... and 7 more" in result
        assert "Error 9" not in result


class TestWrapExceptions:
    """Tests for wrap_exceptions context manager."""
    
    def test_wraps_generic_exception(self):
        """GIVEN: Code that raises generic Exception
        WHEN: Wrapped in wrap_exceptions
        THEN: Raises specified OptimizerError with original as cause
        """
        with pytest.raises(ExtractionError) as exc_info:
            with wrap_exceptions(ExtractionError, "Extraction failed", details={"foo": "bar"}):
                raise ValueError("Original error")
        
        exc = exc_info.value
        assert exc.message == "Extraction failed"
        assert exc.details == {"foo": "bar"}
        assert isinstance(exc.__cause__, ValueError)
        assert str(exc.__cause__) == "Original error"
    
    def test_preserves_optimizer_error(self):
        """GIVEN: Code that raises OptimizerError
        WHEN: Wrapped in wrap_exceptions
        THEN: Original OptimizerError is re-raised as-is
        """
        original = ValidationError("Original validation error")
        
        with pytest.raises(ValidationError) as exc_info:
            with wrap_exceptions(ExtractionError, "Should not wrap"):
                raise original
        
        assert exc_info.value is original
    
    def test_no_exception(self):
        """GIVEN: Code that doesn't raise exception
        WHEN: Wrapped in wrap_exceptions
        THEN: Executes normally
        """
        with wrap_exceptions(ExtractionError, "Should not raise"):
            x = 42
        
        assert x == 42
    
    def test_reraise_false(self):
        """GIVEN: reraise=False
        WHEN: Exception is wrapped
        THEN: Original exception is not set as cause
        """
        with pytest.raises(ExtractionError) as exc_info:
            with wrap_exceptions(ExtractionError, "Wrapped", reraise=False):
                raise ValueError("Original")
        
        assert exc_info.value.__cause__ is None


class TestExceptionToDict:
    """Tests for exception_to_dict function."""
    
    def test_generic_exception(self):
        """GIVEN: Generic Exception
        WHEN: exception_to_dict called
        THEN: Returns dict with type and message
        """
        exc = ValueError("Invalid value")
        result = exception_to_dict(exc)
        
        assert result["type"] == "ValueError"
        assert result["message"] == "Invalid value"
    
    def test_optimizer_error_with_details(self):
        """GIVEN: OptimizerError with details
        WHEN: exception_to_dict called
        THEN: Returns dict with details field
        """
        exc = ExtractionError("Failed", details={"field": "entities"})
        result = exception_to_dict(exc)
        
        assert result["type"] == "ExtractionError"
        assert result["message"] == "Failed"
        assert result["details"] == {"field": "entities"}
    
    def test_validation_error_with_errors(self):
        """GIVEN: ValidationError with errors list
        WHEN: exception_to_dict called
        THEN: Returns dict with errors field
        """
        exc = ValidationError("Invalid", errors=["Missing id", "Bad type"])
        result = exception_to_dict(exc)
        
        assert result["type"] == "ValidationError"
        assert result["errors"] == ["Missing id", "Bad type"]
    
    def test_proving_error_fields(self):
        """GIVEN: ProvingError with prover and formula
        WHEN: exception_to_dict called
        THEN: Returns dict with prover and formula fields
        """
        exc = ProvingError("Proof failed", prover="z3", formula="P -> Q")
        result = exception_to_dict(exc)
        
        assert result["type"] == "ProvingError"
        assert result["prover"] == "z3"
        assert result["formula"] == "P -> Q"
    
    def test_exception_chain(self):
        """GIVEN: Exception with __cause__ chain
        WHEN: exception_to_dict called
        THEN: Returns dict with nested cause
        """
        cause = ValueError("Root cause")
        try:
            raise ExtractionError("Wrapped") from cause
        except ExtractionError as exc:
            result = exception_to_dict(exc)
        
        assert result["type"] == "ExtractionError"
        assert "cause" in result
        assert result["cause"]["type"] == "ValueError"
        assert result["cause"]["message"] == "Root cause"


class TestSafeErrorHandler:
    """Tests for safe_error_handler decorator."""
    
    def test_catches_specified_exceptions(self):
        """GIVEN: Function that raises ValueError
        WHEN: Decorated with @safe_error_handler(ValueError, default=[])
        THEN: Returns default instead of raising
        """
        @safe_error_handler(ValueError, default=[])
        def failing_function():
            raise ValueError("This will be caught")
        
        result = failing_function()
        assert result == []
    
    def test_does_not_catch_other_exceptions(self):
        """GIVEN: Function that raises RuntimeError
        WHEN: Decorated with @safe_error_handler(ValueError)
        THEN: RuntimeError propagates
        """
        @safe_error_handler(ValueError, default=None)
        def failing_function():
            raise RuntimeError("This will not be caught")
        
        with pytest.raises(RuntimeError):
            failing_function()
    
    def test_returns_normally_if_no_exception(self):
        """GIVEN: Function that returns normally
        WHEN: Decorated with @safe_error_handler
        THEN: Returns normal value
        """
        @safe_error_handler(ValueError, default=None)
        def working_function():
            return 42
        
        result = working_function()
        assert result == 42
    
    def test_multiple_exception_types(self):
        """GIVEN: Function that might raise multiple exception types
        WHEN: Decorated with @safe_error_handler(ValueError, KeyError)
        THEN: Catches all specified types
        """
        @safe_error_handler(ValueError, KeyError, default="default")
        def sometimes_fails(which):
            if which == "value":
                raise ValueError()
            elif which == "key":
                raise KeyError()
            return "success"
        
        assert sometimes_fails("value") == "default"
        assert sometimes_fails("key") == "default"
        assert sometimes_fails("none") == "success"
    
    def test_default_catches_all(self):
        """GIVEN: @safe_error_handler with no exception types
        WHEN: Any exception is raised
        THEN: Catches it and returns default
        """
        @safe_error_handler(default="safe")
        def failing_function():
            raise RuntimeError("Any exception")
        
        result = failing_function()
        assert result == "safe"
    
    def test_logs_caught_exceptions(self, caplog):
        """GIVEN: Function that raises caught exception
        WHEN: Decorated with @safe_error_handler
        THEN: Logs the exception at specified level
        """
        @safe_error_handler(ValueError, default=None, log_level=logging.WARNING)
        def failing_function():
            raise ValueError("Test error")
        
        with caplog.at_level(logging.WARNING):
            result = failing_function()
        
        assert result is None
        assert "failing_function raised ValueError" in caplog.text
        assert "Test error" in caplog.text
