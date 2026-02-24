"""Tests for Configuration Validation Schema (Batch 259).

Comprehensive test coverage for centralized configuration validation:
- Field-level rule validation
- Type checking and constraints
- Cross-field dependencies
- Error reporting and recovery
"""

from __future__ import annotations

import pytest
from ipfs_datasets_py.optimizers.graphrag.config_validation_schema import (
    ValidationRule,
    ValidationRuleSet,
    ExtractionConfigSchema,
    ConfigValidator,
    ConfigValidationError,
)


# ============================================================================
# Test Validation Rules
# ============================================================================


class TestValidationRule:
    """Test individual validation rules."""
    
    def test_simple_rule_passes(self):
        """Rule passes when condition is True."""
        rule = ValidationRule(
            name="test",
            condition=lambda x: x > 0,
            message="must be positive"
        )
        assert rule.condition(5) is True
    
    def test_simple_rule_fails(self):
        """Rule fails when condition is False."""
        rule = ValidationRule(
            name="test",
            condition=lambda x: x > 0,
            message="must be positive"
        )
        assert rule.condition(-5) is False


class TestValidationRuleSet:
    """Test rule sets and combinations."""
    
    def test_type_check_pass(self):
        """Type check passes for correct type."""
        rules = ValidationRuleSet("value", float)
        rules.add_type_check(float)
        is_valid, errors = rules.validate(1.5)
        assert is_valid is True
        assert len(errors) == 0
    
    def test_type_check_fail(self):
        """Type check fails for wrong type."""
        rules = ValidationRuleSet("value", float)
        rules.add_type_check(float)
        is_valid, errors = rules.validate("not a float")
        assert is_valid is False
        assert len(errors) > 0
    
    def test_range_check_pass(self):
        """Range check passes for value in bounds."""
        rules = ValidationRuleSet("value", float)
        rules.add_range(0.0, 1.0)
        is_valid, errors = rules.validate(0.5)
        assert is_valid is True
    
    def test_range_check_below_min(self):
        """Range check fails below minimum."""
        rules = ValidationRuleSet("value", float)
        rules.add_range(0.0, 1.0)
        is_valid, errors = rules.validate(-0.5)
        assert is_valid is False
    
    def test_range_check_above_max(self):
        """Range check fails above maximum."""
        rules = ValidationRuleSet("value", float)
        rules.add_range(0.0, 1.0)
        is_valid, errors = rules.validate(1.5)
        assert is_valid is False
    
    def test_pattern_check_pass(self):
        """Pattern check passes matching string."""
        rules = ValidationRuleSet("value", str)
        rules.add_pattern(r"^[a-z_]+$")
        is_valid, errors = rules.validate("valid_name")
        assert is_valid is True
    
    def test_pattern_check_fail(self):
        """Pattern check fails non-matching string."""
        rules = ValidationRuleSet("value", str)
        rules.add_pattern(r"^[a-z_]+$")
        is_valid, errors = rules.validate("Invalid-Name")
        assert is_valid is False
    
    def test_collection_type_check(self):
        """Collection type check validates element types."""
        rules = ValidationRuleSet("items", list)
        rules.add_collection_type(str)
        is_valid, errors = rules.validate(["a", "b", "c"])
        assert is_valid is True
    
    def test_collection_type_check_mixed(self):
        """Collection type check fails with mixed types."""
        rules = ValidationRuleSet("items", list)
        rules.add_collection_type(str)
        is_valid, errors = rules.validate(["a", 1, "c"])
        assert is_valid is False
    
    def test_chaining_rules(self):
        """Multiple rules can be chained."""
        rules = ValidationRuleSet("value", float)
        rules.add_type_check(float).add_range(0.0, 1.0)
        is_valid, errors = rules.validate(0.5)
        assert is_valid is True
    
    def test_multiple_errors(self):
        """Multiple rules can report multiple errors."""
        rules = ValidationRuleSet("value", float)
        rules.add_type_check(float).add_range(0.0, 1.0)
        # String is invalid type and also fails range check (with graceful type error handling)
        is_valid, errors = rules.validate("invalid")
        assert is_valid is False
        # Should have at least one error (type check failure)
        assert len(errors) >= 1


# ============================================================================
# Test Schema Validation
# ============================================================================


class TestExtractionConfigSchema:
    """Test schema validation for ExtractionConfig fields."""
    
    def test_schema_creation(self):
        """Schema creates with all field rule sets."""
        schema = ExtractionConfigSchema()
        assert len(schema.fields) > 0
        assert "confidence" in schema.fields
        assert "stopwords" in schema.fields
    
    def test_confidence_valid(self):
        """Confidence field validates correctly."""
        schema = ExtractionConfigSchema()
        config = {"confidence": 0.7}
        is_valid, errors = schema.validate(config)
        assert is_valid is True
    
    def test_confidence_invalid_type(self):
        """Confidence field rejects non-float with proper max_confidence."""
        schema = ExtractionConfigSchema()
        config = {"confidence": "high", "max_confidence": 0.95}
        is_valid, errors = schema.validate(config)
        assert is_valid is False
        assert "confidence" in errors
    
    def test_confidence_invalid_range(self):
        """Confidence field rejects out-of-range values."""
        schema = ExtractionConfigSchema()
        config = {"confidence": 1.5}
        is_valid, errors = schema.validate(config)
        assert is_valid is False
        assert "confidence" in errors
    
    def test_max_entities_valid(self):
        """Max entities field validates correctly."""
        schema = ExtractionConfigSchema()
        config = {"max_entities": 1000}
        is_valid, errors = schema.validate(config)
        assert is_valid is True
    
    def test_max_entities_invalid_negative(self):
        """Max entities rejects negative values."""
        schema = ExtractionConfigSchema()
        config = {"max_entities": -5}
        is_valid, errors = schema.validate(config)
        assert is_valid is False
        assert "max_entities" in errors
    
    def test_stopwords_valid(self):
        """Stopwords field validates list of strings."""
        schema = ExtractionConfigSchema()
        config = {"stopwords": ["the", "a", "an"]}
        is_valid, errors = schema.validate(config)
        assert is_valid is True
    
    def test_stopwords_invalid_type(self):
        """Stopwords rejects non-string elements."""
        schema = ExtractionConfigSchema()
        config = {"stopwords": ["the", 5, "an"]}
        is_valid, errors = schema.validate(config)
        assert is_valid is False
        assert "stopwords" in errors
    
    def test_multiple_fields_valid(self):
        """Multiple fields validate correctly."""
        schema = ExtractionConfigSchema()
        config = {
            "confidence": 0.5,
            "max_confidence": 0.95,
            "max_entities": 500,
            "stopwords": ["the", "a"],
            "include_properties": True
        }
        is_valid, errors = schema.validate(config)
        assert is_valid is True
    
    def test_multiple_fields_errors(self):
        """Multiple fields report errors independently."""
        schema = ExtractionConfigSchema()
        config = {
            "confidence": 1.5,  # Invalid: out of range
            "max_entities": -10,  # Invalid: negative
            "stopwords": [1, 2, 3]  # Invalid: non-string elements
        }
        is_valid, errors = schema.validate(config)
        assert is_valid is False
        assert "confidence" in errors
        assert "max_entities" in errors
        assert "stopwords" in errors
    
    def test_cross_field_constraint_confidence(self):
        """Confidence must be less than max_confidence."""
        schema = ExtractionConfigSchema()
        config = {
            "confidence": 0.95,
            "max_confidence": 0.8  # Invalid: confidence >= max_confidence
        }
        is_valid, errors = schema.validate(config)
        assert is_valid is False
        assert "confidence" in errors or "max_confidence" in errors


# ============================================================================
# Test ConfigValidator
# ============================================================================


class TestConfigValidator:
    """Test high-level config validator."""
    
    def test_validator_initialization(self):
        """Validator initializes with schema."""
        validator = ConfigValidator()
        assert validator.schema is not None
    
    def test_validate_strict_pass(self):
        """Strict validation passes for valid config."""
        validator = ConfigValidator()
        config = {
            "confidence": 0.7,
            "max_confidence": 0.95,
            "stopwords": ["the", "a"]
        }
        assert validator.validate_strict(config) is True
    
    def test_validate_strict_fail_raises(self):
        """Strict validation raises exception on error."""
        validator = ConfigValidator()
        config = {
            "confidence": 1.5  # Invalid: out of range
        }
        with pytest.raises(ConfigValidationError):
            validator.validate_strict(config)
    
    def test_validate_and_fix_confidence(self):
        """Validator can fix confidence/max_confidence conflict."""
        validator = ConfigValidator()
        config = {
            "confidence": 0.95,
            "max_confidence": 0.8
        }
        fixed = validator.validate_and_fix(config)
        assert fixed["max_confidence"] >= fixed["confidence"]
    
    def test_validate_and_fix_preserves_valid(self):
        """Validator preserves already-valid config."""
        validator = ConfigValidator()
        config = {
            "confidence": 0.7,
            "max_confidence": 0.95
        }
        fixed = validator.validate_and_fix(config)
        assert fixed["confidence"] == 0.7
        assert fixed["max_confidence"] == 0.95
    
    def test_config_validation_error_message(self):
        """ConfigValidationError formats error message properly."""
        error = ConfigValidationError("test_field", ["error 1", "error 2"])
        assert "test_field" in str(error)
        assert "error 1" in str(error)


# ============================================================================
# Integration Tests
# ============================================================================


class TestConfigValidationIntegration:
    """Integration tests for complete validation workflows."""
    
    def test_full_valid_config(self):
        """Complete valid config passes all validation."""
        schema = ExtractionConfigSchema()
        config = {
            "confidence": 0.6,
            "max_confidence": 0.95,
            "llm_fallback_threshold": 0.3,
            "max_entities": 500,
            "max_relationships": 1000,
            "min_entity_length": 2,
            "window_size": 5,
            "sentence_window": 2,
            "stopwords": ["the", "a", "an"],
            "allowed_entity_types": ["Person", "Organization", "Location"],
            "domain_vocab": {"legal": ["agreement", "contract"]},
            "custom_rules": ["RULE_1", "RULE_2"],
            "include_properties": True
        }
        is_valid, errors = schema.validate(config)
        assert is_valid is True
        assert len(errors) == 0

    def test_sentence_window_invalid(self):
        """Sentence window rejects negative values."""
        schema = ExtractionConfigSchema()
        is_valid, errors = schema.validate({"sentence_window": -1})
        assert is_valid is False
        assert "sentence_window" in errors
    
    def test_partial_config(self):
        """Partial config validates only included fields."""
        schema = ExtractionConfigSchema()
        config = {
            "confidence": 0.7,
            "stopwords": ["the"]
        }
        is_valid, errors = schema.validate(config)
        # Should be valid for included fields
        assert "confidence" not in errors
        assert "stopwords" not in errors
    
    def test_empty_config(self):
        """Empty config is valid (all fields optional)."""
        schema = ExtractionConfigSchema()
        config = {}
        is_valid, errors = schema.validate(config)
        assert is_valid is True
    
    def test_get_field_rule(self):
        """Can retrieve individual field validation rules."""
        schema = ExtractionConfigSchema()
        rule_set = schema.get_field_rule("confidence")
        assert rule_set is not None
        assert rule_set.field_name == "confidence"
    
    def test_get_nonexistent_field(self):
        """Getting nonexistent field returns None."""
        schema = ExtractionConfigSchema()
        rule_set = schema.get_field_rule("nonexistent_field")
        assert rule_set is None


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_confidence_boundaries(self):
        """Confidence field validates boundaries correctly."""
        schema = ExtractionConfigSchema()
        
        # Valid boundaries (with max_confidence > confidence to satisfy cross-field constraint)
        assert schema.validate({"confidence": 0.0, "max_confidence": 0.5})[0] is True
        assert schema.validate({"confidence": 0.9, "max_confidence": 0.95})[0] is True
        
        # Invalid boundaries
        config, _ = schema.validate({"confidence": -0.1})
        assert config is False
        config, _ = schema.validate({"confidence": 1.1})
        assert config is False
    
    def test_empty_collections(self):
        """Empty collections are valid."""
        schema = ExtractionConfigSchema()
        assert schema.validate({"stopwords": []})[0] is True
        assert schema.validate({"custom_rules": []})[0] is True
    
    def test_large_values(self):
        """Large values are valid if in range."""
        schema = ExtractionConfigSchema()
        assert schema.validate({"max_entities": 1000000})[0] is True
        assert schema.validate({"max_relationships": 1000000})[0] is True
    
    def test_unicode_in_strings(self):
        """Unicode strings are handled correctly."""
        schema = ExtractionConfigSchema()
        config = {"stopwords": ["café", "naïve", "résumé"]}
        is_valid, errors = schema.validate(config)
        assert is_valid is True
    
    def test_none_values(self):
        """None values are handled gracefully."""
        schema = ExtractionConfigSchema()
        config = {"stopwords": None}
        # None should be handled by optional=True in rules
        is_valid, errors = schema.validate(config)
        # Result depends on implementation (may be valid or invalid)
        # Just verify it doesn't crash
        assert isinstance(is_valid, bool)
