"""
Test suite for core/file_validator/_validation_result.py converted from unittest to pytest.
"""
import pytest
from pydantic import ValidationError

try:
    from core.file_validator._validation_result import ValidationResult
except ImportError:
    pytest.skip("core.file_validator._validation_result module not available", allow_module_level=True)


class TestValidationResultInitialization:
    """Test ValidationResult initialization and BaseModel behavior."""

    def test_init_with_all_valid_parameters_creates_instance(self):
        """
        GIVEN valid parameters:
            - is_valid: True
            - errors: ['error1', 'error2']
            - warnings: ['warning1']
            - validation_context: {'key': 'value'}
        WHEN ValidationResult is initialized
        THEN expect:
            - Instance created successfully
        """
        # GIVEN
        is_valid = True
        errors = ['error1', 'error2']
        warnings = ['warning1']
        validation_context = {'key': 'value'}
        
        # WHEN
        result = ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            validation_context=validation_context
        )
        
        # THEN
        assert isinstance(result, ValidationResult)

    def test_init_with_all_valid_parameters_sets_is_valid(self):
        """
        GIVEN valid parameters with is_valid: True
        WHEN ValidationResult is initialized
        THEN expect:
            - is_valid is True
        """
        # GIVEN
        is_valid = True
        errors = ['error1', 'error2']
        warnings = ['warning1']
        validation_context = {'key': 'value'}
        
        # WHEN
        result = ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            validation_context=validation_context
        )
        
        # THEN
        assert result.is_valid is True

    def test_init_with_all_valid_parameters_sets_errors(self):
        """
        GIVEN valid parameters with errors: ['error1', 'error2']
        WHEN ValidationResult is initialized
        THEN expect:
            - errors list contains provided errors
        """
        # GIVEN
        is_valid = True
        errors = ['error1', 'error2']
        warnings = ['warning1']
        validation_context = {'key': 'value'}
        
        # WHEN
        result = ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            validation_context=validation_context
        )
        
        # THEN
        assert result.errors == ['error1', 'error2']

    def test_init_with_all_valid_parameters_sets_warnings(self):
        """
        GIVEN valid parameters with warnings: ['warning1']
        WHEN ValidationResult is initialized
        THEN expect:
            - warnings list contains provided warnings
        """
        # GIVEN
        is_valid = True
        errors = ['error1', 'error2']
        warnings = ['warning1']
        validation_context = {'key': 'value'}
        
        # WHEN
        result = ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            validation_context=validation_context
        )
        
        # THEN
        assert result.warnings == ['warning1']

    def test_init_with_all_valid_parameters_sets_validation_context(self):
        """
        GIVEN valid parameters with validation_context: {'key': 'value'}
        WHEN ValidationResult is initialized
        THEN expect:
            - validation_context dict contains provided context
        """
        # GIVEN
        is_valid = True
        errors = ['error1', 'error2']
        warnings = ['warning1']
        validation_context = {'key': 'value'}
        
        # WHEN
        result = ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            validation_context=validation_context
        )
        
        # THEN
        assert result.validation_context == {'key': 'value'}

    def test_init_with_minimal_parameters_creates_instance(self):
        """
        GIVEN no parameters
        WHEN ValidationResult is initialized
        THEN expect:
            - Instance created successfully
        """
        # WHEN
        result = ValidationResult()
        
        # THEN
        assert isinstance(result, ValidationResult)

    def test_init_with_minimal_parameters_sets_default_is_valid(self):
        """
        GIVEN no parameters
        WHEN ValidationResult is initialized
        THEN expect:
            - is_valid has default value (True)
        """
        # WHEN
        result = ValidationResult()
        
        # THEN
        assert result.is_valid is True

    def test_init_with_minimal_parameters_sets_default_errors(self):
        """
        GIVEN no parameters
        WHEN ValidationResult is initialized
        THEN expect:
            - errors is empty list
        """
        # WHEN
        result = ValidationResult()
        
        # THEN
        assert result.errors == []

    def test_init_with_minimal_parameters_sets_default_warnings(self):
        """
        GIVEN no parameters
        WHEN ValidationResult is initialized
        THEN expect:
            - warnings is empty list
        """
        # WHEN
        result = ValidationResult()
        
        # THEN
        assert result.warnings == []

    def test_init_with_minimal_parameters_sets_default_validation_context(self):
        """
        GIVEN no parameters
        WHEN ValidationResult is initialized
        THEN expect:
            - validation_context is empty dict
        """
        # WHEN
        result = ValidationResult()
        
        # THEN
        assert result.validation_context == {}

    def test_init_with_invalid_is_valid_type_raises_validation_error(self):
        """
        GIVEN is_valid parameter with non-boolean type (e.g., string)
        WHEN ValidationResult is initialized
        THEN expect:
            - Pydantic ValidationError raised
        """
        # WHEN & THEN
        with pytest.raises(ValidationError):
            ValidationResult(is_valid="not a boolean")

    def test_init_with_invalid_is_valid_type_error_mentions_field(self):
        """
        GIVEN is_valid parameter with non-boolean type (e.g., string)
        WHEN ValidationResult is initialized
        THEN expect:
            - Error indicates type mismatch for is_valid
        """
        # WHEN & THEN
        with pytest.raises(ValidationError) as exc_info:
            ValidationResult(is_valid="not a boolean")
        
        # Verify the error is related to is_valid field
        error_details = str(exc_info.value)
        assert 'is_valid' in error_details.lower()

    def test_init_with_invalid_errors_type_raises_validation_error(self):
        """
        GIVEN errors parameter as non-list type (e.g., string)
        WHEN ValidationResult is initialized
        THEN expect:
            - Pydantic ValidationError raised
        """
        # WHEN & THEN
        with pytest.raises(ValidationError):
            ValidationResult(errors="not a list")

    def test_init_with_invalid_errors_type_error_mentions_field(self):
        """
        GIVEN errors parameter as non-list type (e.g., string)
        WHEN ValidationResult is initialized
        THEN expect:
            - Error indicates type mismatch for errors
        """
        # WHEN & THEN
        with pytest.raises(ValidationError) as exc_info:
            ValidationResult(errors="not a list")
        
        # Verify the error is related to errors field
        error_details = str(exc_info.value)
        assert 'errors' in error_details.lower()

    def test_init_with_invalid_warnings_type_raises_validation_error(self):
        """
        GIVEN warnings parameter as non-list type (e.g., string)
        WHEN ValidationResult is initialized
        THEN expect:
            - Pydantic ValidationError raised
        """
        # WHEN & THEN
        with pytest.raises(ValidationError):
            ValidationResult(warnings="not a list")

    def test_init_with_invalid_warnings_type_error_mentions_field(self):
        """
        GIVEN warnings parameter as non-list type (e.g., string)
        WHEN ValidationResult is initialized
        THEN expect:
            - Error indicates type mismatch for warnings
        """
        # WHEN & THEN
        with pytest.raises(ValidationError) as exc_info:
            ValidationResult(warnings="not a list")
        
        # Verify the error is related to warnings field
        error_details = str(exc_info.value)
        assert 'warnings' in error_details.lower()

    def test_init_with_invalid_validation_context_type_raises_validation_error(self):
        """
        GIVEN validation_context parameter as non-dict type (e.g., list)
        WHEN ValidationResult is initialized
        THEN expect:
            - Pydantic ValidationError raised
        """
        # WHEN & THEN
        with pytest.raises(ValidationError):
            ValidationResult(validation_context=["not", "a", "dict"])

    def test_init_with_invalid_validation_context_type_error_mentions_field(self):
        """
        GIVEN validation_context parameter as non-dict type (e.g., list)
        WHEN ValidationResult is initialized
        THEN expect:
            - Error indicates type mismatch for validation_context
        """
        # WHEN & THEN
        with pytest.raises(ValidationError) as exc_info:
            ValidationResult(validation_context=["not", "a", "dict"])
        
        # Verify the error is related to validation_context field
        error_details = str(exc_info.value)
        assert 'validation_context' in error_details.lower()

    @pytest.mark.parametrize("is_valid,errors,warnings,context", [
        (True, ['error1'], ['warning1'], {'key': 'value'}),
        (False, [], [], {}),
        (True, ['e1', 'e2', 'e3'], ['w1', 'w2'], {'a': 1, 'b': 2}),
        (False, ['critical_error'], [], {'source': 'validation'}),
    ])
    def test_init_with_various_valid_combinations(self, is_valid, errors, warnings, context):
        """
        GIVEN various valid parameter combinations
        WHEN ValidationResult is initialized
        THEN expect:
            - Instance created successfully
            - All fields set correctly
        """
        # WHEN
        result = ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            validation_context=context
        )
        
        # THEN
        assert isinstance(result, ValidationResult)
        assert result.is_valid == is_valid
        assert result.errors == errors
        assert result.warnings == warnings
        assert result.validation_context == context

    def test_init_preserves_list_mutability(self):
        """
        GIVEN mutable lists for errors and warnings
        WHEN ValidationResult is initialized
        THEN expect:
            - Lists can be modified independently
            - Original lists not affected by modifications
        """
        # GIVEN
        original_errors = ['error1']
        original_warnings = ['warning1']
        
        # WHEN
        result = ValidationResult(
            errors=original_errors.copy(),
            warnings=original_warnings.copy()
        )
        
        # Modify the result's lists
        result.errors.append('error2')
        result.warnings.append('warning2')
        
        # THEN
        assert original_errors == ['error1']  # Original unchanged
        assert original_warnings == ['warning1']  # Original unchanged
        assert result.errors == ['error1', 'error2']
        assert result.warnings == ['warning1', 'warning2']