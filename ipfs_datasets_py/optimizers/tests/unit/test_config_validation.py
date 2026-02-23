"""
Tests for Configuration Validation - Batch 236 [arch].

Comprehensive test coverage for centralized configuration validation:
    - ValidationRule field-level checks
    - ConfigValidator orchestration
    - Pre-built validators for ExtractionConfig and OptimizerConfig
    - Cross-field validation logic
    - CompositeValidator integration
    - Error message formatting

Test Coverage:
    - Type checking (int, float, str, bool, list, set, tuple)
    - Range validation (min, max, range_check)
    - Required vs optional fields
    - Allowed discrete values
    - Custom validation functions
    - Cross-field dependencies
    - Partial configuration updates
    - Error message clarity
"""

import pytest
from typing import Tuple

from ipfs_datasets_py.optimizers.common.config_validation import (
    ValidationRule,
    ConfigValidator,
    CompositeValidator,
    create_extraction_config_validator,
    create_optimizer_config_validator,
    create_comprehensive_extraction_validator,
    create_comprehensive_optimizer_validator,
    validate_threshold_relationship,
    validate_entity_limits,
)


# ============================================================================
# Test ValidationRule - Type Checking
# ============================================================================


class TestValidationRuleTypeChecking:
    """Test type validation in ValidationRule."""
    
    def test_int_type_validation_passes(self):
        """Valid integer passes type check."""
        rule = ValidationRule("count", expected_type=int)
        errors = rule.validate(42)
        assert len(errors) == 0
    
    def test_int_type_validation_fails_on_string(self):
        """String fails integer type check."""
        rule = ValidationRule("count", expected_type=int)
        errors = rule.validate("42")
        assert len(errors) == 1
        assert "must be int" in errors[0]
        assert "got str" in errors[0]
    
    def test_float_type_validation_passes(self):
        """Valid float passes type check."""
        rule = ValidationRule("threshold", expected_type=float)
        errors = rule.validate(0.5)
        assert len(errors) == 0
    
    def test_multiple_types_allowed(self):
        """Rule can accept multiple types."""
        rule = ValidationRule("value", expected_type=(int, float))
        
        assert len(rule.validate(42)) == 0  # int valid
        assert len(rule.validate(3.14)) == 0  # float valid
        
        errors = rule.validate("invalid")
        assert len(errors) == 1
        assert "int or float" in errors[0]
    
    def test_none_value_skips_type_check(self):
        """None value bypasses type validation."""
        rule = ValidationRule("optional_field", expected_type=int, required=False)
        errors = rule.validate(None)
        assert len(errors) == 0


# ============================================================================
# Test ValidationRule - Range Checks
# ============================================================================


class TestValidationRuleRangeChecks:
    """Test numeric range validation."""
    
    def test_min_value_validation_passes(self):
        """Value above minimum passes."""
        rule = ValidationRule("count", expected_type=int, min_value=0)
        errors = rule.validate(10)
        assert len(errors) == 0
    
    def test_min_value_validation_fails(self):
        """Value below minimum fails."""
        rule = ValidationRule("count", expected_type=int, min_value=0)
        errors = rule.validate(-5)
        assert len(errors) == 1
        assert "must be >= 0" in errors[0]
    
    def test_max_value_validation_passes(self):
        """Value below maximum passes."""
        rule = ValidationRule("threshold", expected_type=float, max_value=1.0)
        errors = rule.validate(0.7)
        assert len(errors) == 0
    
    def test_max_value_validation_fails(self):
        """Value above maximum fails."""
        rule = ValidationRule("threshold", expected_type=float, max_value=1.0)
        errors = rule.validate(1.5)
        assert len(errors) == 1
        assert "must be <= 1.0" in errors[0]
    
    def test_range_check_validation_passes(self):
        """Value in range passes."""
        rule = ValidationRule("confidence", expected_type=float, range_check=(0.0, 1.0))
        errors = rule.validate(0.5)
        assert len(errors) == 0
    
    def test_range_check_validation_fails_below(self):
        """Value below range fails."""
        rule = ValidationRule("confidence", expected_type=float, range_check=(0.0, 1.0))
        errors = rule.validate(-0.1)
        assert len(errors) == 1
        assert "must be in range [0.0, 1.0]" in errors[0]
    
    def test_range_check_validation_fails_above(self):
        """Value above range fails."""
        rule = ValidationRule("confidence", expected_type=float, range_check=(0.0, 1.0))
        errors = rule.validate(1.5)
        assert len(errors) == 1
        assert "must be in range [0.0, 1.0]" in errors[0]
    
    def test_range_check_on_non_numeric_fails(self):
        """Range check on string produces error."""
        rule = ValidationRule("value", range_check=(0.0, 1.0))
        errors = rule.validate("invalid")
        assert len(errors) >= 1
        assert any("cannot check range" in e for e in errors)


# ============================================================================
# Test ValidationRule - Allowed Values
# ============================================================================


class TestValidationRuleAllowedValues:
    """Test discrete allowed values validation."""
    
    def test_allowed_values_passes(self):
        """Value in allowed set passes."""
        rule = ValidationRule(
            "log_level",
            expected_type=str,
            allowed_values={"DEBUG", "INFO", "WARNING", "ERROR"},
        )
        errors = rule.validate("INFO")
        assert len(errors) == 0
    
    def test_allowed_values_fails(self):
        """Value not in allowed set fails."""
        rule = ValidationRule(
            "log_level",
            expected_type=str,
            allowed_values={"DEBUG", "INFO", "WARNING", "ERROR"},
        )
        errors = rule.validate("TRACE")
        assert len(errors) == 1
        assert "must be one of" in errors[0]
        assert "DEBUG" in errors[0]
    
    def test_allowed_values_with_integers(self):
        """Allowed values work with integers."""
        rule = ValidationRule(
            "priority",
            expected_type=int,
            allowed_values={1, 2, 3, 5, 8},
        )
        
        assert len(rule.validate(3)) == 0
        errors = rule.validate(4)
        assert len(errors) == 1
        assert "must be one of" in errors[0]


# ============================================================================
# Test ValidationRule - Custom Validators
# ============================================================================


class TestValidationRuleCustomValidators:
    """Test custom validation functions."""
    
    def test_custom_validator_passes(self):
        """Custom validator returns True for valid value."""
        def is_even(value: int) -> Tuple[bool, str]:
            if value % 2 == 0:
                return True, ""
            return False, "Value must be even"
        
        rule = ValidationRule("count", expected_type=int, custom_validator=is_even)
        errors = rule.validate(4)
        assert len(errors) == 0
    
    def test_custom_validator_fails(self):
        """Custom validator returns False for invalid value."""
        def is_even(value: int) -> Tuple[bool, str]:
            if value % 2 == 0:
                return True, ""
            return False, "Value must be even"
        
        rule = ValidationRule("count", expected_type=int, custom_validator=is_even)
        errors = rule.validate(3)
        assert len(errors) == 1
        assert "failed validation" in errors[0]
        assert "must be even" in errors[0]
    
    def test_custom_error_message_override(self):
        """Custom error message replaces default."""
        rule = ValidationRule(
            "threshold",
            expected_type=float,
            range_check=(0.0, 1.0),
            error_message="Threshold {value} is invalid for field {field}",
        )
        errors = rule.validate(1.5)
        assert len(errors) == 1
        assert "Threshold 1.5 is invalid" in errors[0]


# ============================================================================
# Test ConfigValidator - Required Fields
# ============================================================================


class TestConfigValidatorRequiredFields:
    """Test required field validation."""
    
    def test_required_field_present_passes(self):
        """Configuration with required field passes."""
        validator = ConfigValidator([
            ValidationRule("max_rounds", expected_type=int, required=True),
        ])
        
        config = {"max_rounds": 10}
        errors = validator.validate(config)
        assert len(errors) == 0
    
    def test_required_field_missing_fails(self):
        """Configuration missing required field fails."""
        validator = ConfigValidator([
            ValidationRule("max_rounds", expected_type=int, required=True),
        ])
        
        config = {}
        errors = validator.validate(config)
        assert len(errors) == 1
        assert "Required field 'max_rounds' is missing" in errors[0]
    
    def test_optional_field_missing_passes(self):
        """Configuration missing optional field passes."""
        validator = ConfigValidator([
            ValidationRule("timeout", expected_type=int, required=False),
        ])
        
        config = {}
        errors = validator.validate(config)
        assert len(errors) == 0
    
    def test_multiple_required_fields(self):
        """Multiple required fields checked."""
        validator = ConfigValidator([
            ValidationRule("max_rounds", expected_type=int, required=True),
            ValidationRule("threshold", expected_type=float, required=True),
        ])
        
        config = {"max_rounds": 10}
        errors = validator.validate(config)
        assert len(errors) == 1
        assert "threshold" in errors[0]


# ============================================================================
# Test ConfigValidator - Field Validation
# ============================================================================


class TestConfigValidatorFieldValidation:
    """Test field-level validation."""
    
    def test_all_fields_valid_passes(self):
        """Configuration with all valid fields passes."""
        validator = ConfigValidator([
            ValidationRule("count", expected_type=int, min_value=0),
            ValidationRule("threshold", expected_type=float, range_check=(0.0, 1.0)),
        ])
        
        config = {"count": 5, "threshold": 0.7}
        errors = validator.validate(config)
        assert len(errors) == 0
    
    def test_invalid_field_fails(self):
        """Configuration with invalid field fails."""
        validator = ConfigValidator([
            ValidationRule("threshold", expected_type=float, range_check=(0.0, 1.0)),
        ])
        
        config = {"threshold": 1.5}
        errors = validator.validate(config)
        assert len(errors) == 1
        assert "threshold" in errors[0]
        assert "range" in errors[0]
    
    def test_multiple_field_errors(self):
        """Multiple field validations can fail."""
        validator = ConfigValidator([
            ValidationRule("count", expected_type=int, min_value=0),
            ValidationRule("threshold", expected_type=float, range_check=(0.0, 1.0)),
        ])
        
        config = {"count": -5, "threshold": 2.0}
        errors = validator.validate(config)
        assert len(errors) == 2
    
    def test_is_valid_returns_true_for_valid_config(self):
        """is_valid returns True for valid configuration."""
        validator = ConfigValidator([
            ValidationRule("count", expected_type=int, min_value=0),
        ])
        
        config = {"count": 10}
        assert validator.is_valid(config) is True
    
    def test_is_valid_returns_false_for_invalid_config(self):
        """is_valid returns False for invalid configuration."""
        validator = ConfigValidator([
            ValidationRule("count", expected_type=int, min_value=0),
        ])
        
        config = {"count": -5}
        assert validator.is_valid(config) is False


# ============================================================================
# Test ConfigValidator - Partial Validation
# ============================================================================


class TestConfigValidatorPartialValidation:
    """Test partial configuration validation."""
    
    def test_validate_partial_ignores_missing_required(self):
        """Partial validation ignores missing required fields."""
        validator = ConfigValidator([
            ValidationRule("max_rounds", expected_type=int, required=True),
            ValidationRule("threshold", expected_type=float, required=True),
        ])
        
        config = {"threshold": 0.5}  # Missing max_rounds
        errors = validator.validate_partial(config)
        assert len(errors) == 0  # No error for missing max_rounds
    
    def test_validate_partial_checks_present_fields(self):
        """Partial validation still checks present fields."""
        validator = ConfigValidator([
            ValidationRule("threshold", expected_type=float, range_check=(0.0, 1.0)),
        ])
        
        config = {"threshold": 1.5}
        errors = validator.validate_partial(config)
        assert len(errors) == 1
        assert "range" in errors[0]
    
    def test_validate_partial_with_multiple_fields(self):
        """Partial validation works with multiple fields."""
        validator = ConfigValidator([
            ValidationRule("count", expected_type=int, min_value=0),
            ValidationRule("threshold", expected_type=float, range_check=(0.0, 1.0)),
            ValidationRule("name", expected_type=str, required=True),
        ])
        
        config = {"count": 5, "threshold": 0.7}  # Missing name
        errors = validator.validate_partial(config)
        assert len(errors) == 0


# ============================================================================
# Test ConfigValidator - Dynamic Rules
# ============================================================================


class TestConfigValidatorDynamicRules:
    """Test adding/removing rules dynamically."""
    
    def test_add_rule_dynamically(self):
        """Rules can be added after initialization."""
        validator = ConfigValidator([
            ValidationRule("count", expected_type=int),
        ])
        
        # Initially threshold not checked
        config = {"count": 5, "threshold": 1.5}
        errors = validator.validate_partial(config)
        assert len(errors) == 0
        
        # Add threshold rule
        validator.add_rule(
            ValidationRule("threshold", expected_type=float, range_check=(0.0, 1.0))
        )
        
        errors = validator.validate_partial(config)
        assert len(errors) == 1
        assert "threshold" in errors[0]
    
    def test_remove_rule_dynamically(self):
        """Rules can be removed after initialization."""
        validator = ConfigValidator([
            ValidationRule("count", expected_type=int, min_value=0),
        ])
        
        config = {"count": -5}
        assert len(validator.validate(config)) == 1
        
        # Remove rule
        validator.remove_rule("count")
        
        errors = validator.validate(config)
        assert len(errors) == 0


# ============================================================================
# Test Pre-built Validators
# ============================================================================


class TestPrebuiltValidators:
    """Test pre-built validators for common config types."""
    
    def test_extraction_config_validator_valid(self):
        """Valid extraction config passes."""
        validator = create_extraction_config_validator()
        
        config = {
            "confidence_threshold": 0.5,
            "max_entities": 100,
            "min_entity_length": 2,
            "include_properties": True,
        }
        
        errors = validator.validate_partial(config)
        assert len(errors) == 0
    
    def test_extraction_config_validator_invalid_threshold(self):
        """Invalid threshold fails extraction config validation."""
        validator = create_extraction_config_validator()
        
        config = {"confidence_threshold": 1.5}
        errors = validator.validate_partial(config)
        assert len(errors) == 1
        assert "confidence_threshold" in errors[0]
    
    def test_optimizer_config_validator_valid(self):
        """Valid optimizer config passes."""
        validator = create_optimizer_config_validator()
        
        config = {
            "max_rounds": 10,
            "convergence_threshold": 0.01,
            "enable_caching": True,
            "log_level": "INFO",
        }
        
        errors = validator.validate(config)
        assert len(errors) == 0
    
    def test_optimizer_config_validator_invalid_log_level(self):
        """Invalid log level fails optimizer config validation."""
        validator = create_optimizer_config_validator()
        
        config = {
            "max_rounds": 10,
            "convergence_threshold": 0.01,
            "log_level": "TRACE",  # Not in allowed values
        }
        
        errors = validator.validate(config)
        assert len(errors) == 1
        assert "log_level" in errors[0]
    
    def test_optimizer_config_validator_missing_required(self):
        """Missing required field fails optimizer config validation."""
        validator = create_optimizer_config_validator()
        
        config = {"max_rounds": 10}  # Missing convergence_threshold
        errors = validator.validate(config)
        assert len(errors) == 1
        assert "convergence_threshold" in errors[0]


# ============================================================================
# Test Cross-Field Validators
# ============================================================================


class TestCrossFieldValidators:
    """Test cross-field validation functions."""
    
    def test_threshold_relationship_valid(self):
        """Valid threshold relationship passes."""
        config = {
            "confidence_threshold": 0.3,
            "max_confidence": 0.9,
        }
        
        errors = validate_threshold_relationship(config)
        assert len(errors) == 0
    
    def test_threshold_relationship_invalid(self):
        """Invalid threshold relationship fails."""
        config = {
            "confidence_threshold": 0.9,
            "max_confidence": 0.3,
        }
        
        errors = validate_threshold_relationship(config)
        assert len(errors) == 1
        assert "confidence_threshold" in errors[0]
        assert "max_confidence" in errors[0]
    
    def test_threshold_relationship_missing_field(self):
        """Missing field in threshold relationship is ignored."""
        config = {"confidence_threshold": 0.9}
        errors = validate_threshold_relationship(config)
        assert len(errors) == 0
    
    def test_entity_limits_valid(self):
        """Valid entity limits pass."""
        config = {
            "max_entities": 1000,
            "max_relationships": 5000,
        }
        
        errors = validate_entity_limits(config)
        assert len(errors) == 0
    
    def test_entity_limits_exceeds_recommended_entities(self):
        """Entity limit exceeding recommendation produces warning."""
        config = {"max_entities": 200000}
        errors = validate_entity_limits(config)
        assert len(errors) == 1
        assert "max_entities" in errors[0]
        assert "recommended limit" in errors[0]
    
    def test_entity_limits_exceeds_recommended_relationships(self):
        """Relationship limit exceeding recommendation produces warning."""
        config = {"max_relationships": 2000000}
        errors = validate_entity_limits(config)
        assert len(errors) == 1
        assert "max_relationships" in errors[0]


# ============================================================================
# Test CompositeValidator
# ============================================================================


class TestCompositeValidator:
    """Test composite validator combining field and cross-field checks."""
    
    def test_composite_validator_all_valid(self):
        """Valid config passes composite validation."""
        field_validator = ConfigValidator([
            ValidationRule("confidence_threshold", expected_type=float, range_check=(0.0, 1.0)),
            ValidationRule("max_confidence", expected_type=float, range_check=(0.0, 1.0)),
        ])
        
        composite = CompositeValidator(
            field_validator,
            [validate_threshold_relationship],
        )
        
        config = {
            "confidence_threshold": 0.3,
            "max_confidence": 0.9,
        }
        
        errors = composite.validate(config)
        assert len(errors) == 0
    
    def test_composite_validator_field_error(self):
        """Field validation error caught by composite."""
        field_validator = ConfigValidator([
            ValidationRule("confidence_threshold", expected_type=float, range_check=(0.0, 1.0)),
        ])
        
        composite = CompositeValidator(field_validator, [])
        
        config = {"confidence_threshold": 1.5}
        errors = composite.validate(config)
        assert len(errors) == 1
        assert "range" in errors[0]
    
    def test_composite_validator_cross_field_error(self):
        """Cross-field validation error caught by composite."""
        field_validator = ConfigValidator([
            ValidationRule("confidence_threshold", expected_type=float, range_check=(0.0, 1.0)),
            ValidationRule("max_confidence", expected_type=float, range_check=(0.0, 1.0)),
        ])
        
        composite = CompositeValidator(
            field_validator,
            [validate_threshold_relationship],
        )
        
        config = {
            "confidence_threshold": 0.9,
            "max_confidence": 0.3,
        }
        
        errors = composite.validate(config)
        assert len(errors) == 1
        assert "confidence_threshold" in errors[0]
    
    def test_composite_validator_multiple_errors(self):
        """Multiple errors from field and cross-field checks."""
        field_validator = ConfigValidator([
            ValidationRule("confidence_threshold", expected_type=float, range_check=(0.0, 1.0)),
            ValidationRule("max_confidence", expected_type=float, range_check=(0.0, 1.0)),
            ValidationRule("max_entities", expected_type=int, min_value=0),
        ])
        
        composite = CompositeValidator(
            field_validator,
            [validate_threshold_relationship, validate_entity_limits],
        )
        
        config = {
            "confidence_threshold": 1.5,  # Out of range
            "max_confidence": 0.3,  # Creates cross-field error
            "max_entities": 200000,  # Exceeds recommended
        }
        
        errors = composite.validate(config)
        assert len(errors) >= 3  # At least 3 errors
    
    def test_comprehensive_extraction_validator(self):
        """Comprehensive extraction validator works end-to-end."""
        validator = create_comprehensive_extraction_validator()
        
        config = {
            "confidence_threshold": 0.3,
            "max_confidence": 0.9,
            "max_entities": 1000,
        }
        
        assert validator.is_valid(config) is True
    
    def test_comprehensive_optimizer_validator(self):
        """Comprehensive optimizer validator works end-to-end."""
        validator = create_comprehensive_optimizer_validator()
        
        config = {
            "max_rounds": 10,
            "convergence_threshold": 0.01,
            "log_level": "INFO",
        }
        
        assert validator.is_valid(config) is True


# ============================================================================
# Test Error Message Quality
# ============================================================================


class TestErrorMessageQuality:
    """Test that error messages are clear and actionable."""
    
    def test_error_message_includes_field_name(self):
        """Error message includes field name."""
        rule = ValidationRule("threshold", expected_type=float, range_check=(0.0, 1.0))
        errors = rule.validate(1.5)
        assert "threshold" in errors[0]
    
    def test_error_message_includes_expected_type(self):
        """Error message includes expected type."""
        rule = ValidationRule("count", expected_type=int)
        errors = rule.validate("invalid")
        assert "int" in errors[0]
        assert "str" in errors[0]
    
    def test_error_message_includes_actual_value(self):
        """Error message includes actual invalid value."""
        rule = ValidationRule("threshold", expected_type=float, range_check=(0.0, 1.0))
        errors = rule.validate(1.5)
        assert "1.5" in errors[0]
    
    def test_error_message_includes_constraints(self):
        """Error message includes validation constraints."""
        rule = ValidationRule("count", expected_type=int, min_value=0, max_value=100)
        errors = rule.validate(150)
        assert "100" in errors[0]
        assert "<=" in errors[0]
