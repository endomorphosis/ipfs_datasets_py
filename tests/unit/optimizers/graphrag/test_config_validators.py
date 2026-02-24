"""
Tests for configuration schema validation utilities.

This test suite covers:
- Field constraints (type, range, enum)
- Configuration validation
- Dependency checking
- Issue detection and suggestions
- Configuration merging
- ExtractionConfig and OptimizerConfig specific validation
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.config_validators import (
    FieldConstraint,
    ConfigValidator,
    ExtractionConfigValidator,
    OptimizerConfigValidator,
    ValidationError,
    ValidationResult,
    detect_configuration_issues,
    merge_config_with_defaults,
)


class TestFieldConstraint:
    """Tests for field constraints."""
    
    def test_type_check_valid(self):
        """Test type check passes for valid type."""
        constraint = FieldConstraint('test').type_check(str)
        result = constraint.validate('hello')
        assert result is None
    
    def test_type_check_invalid(self):
        """Test type check fails for invalid type."""
        constraint = FieldConstraint('test').type_check(str)
        result = constraint.validate(123)
        assert result is not None
        assert any('Expected str' in err for err in result)
    
    def test_range_check_valid(self):
        """Test range check passes for valid range."""
        constraint = FieldConstraint('test').range_check(0, 100)
        result = constraint.validate(50)
        assert result is None
    
    def test_range_check_below_min(self):
        """Test range check fails below minimum."""
        constraint = FieldConstraint('test').range_check(0, 100)
        result = constraint.validate(-10)
        assert result is not None
        assert any('must be >= 0' in err.lower() for err in result)
    
    def test_range_check_above_max(self):
        """Test range check fails above maximum."""
        constraint = FieldConstraint('test').range_check(0, 100)
        result = constraint.validate(150)
        assert result is not None
        assert any('must be <= 100' in err.lower() for err in result)
    
    def test_enum_check_valid(self):
        """Test enum check passes for valid value."""
        constraint = FieldConstraint('test').enum_check(['a', 'b', 'c'])
        result = constraint.validate('b')
        assert result is None
    
    def test_enum_check_invalid(self):
        """Test enum check fails for invalid value."""
        constraint = FieldConstraint('test').enum_check(['a', 'b', 'c'])
        result = constraint.validate('d')
        assert result is not None
        assert any('must be one of' in err.lower() for err in result)
    
    def test_custom_validator(self):
        """Test custom validator function."""
        def custom_val(value):
            return "error" if value == 0 else None
        
        constraint = FieldConstraint('test').custom(custom_val)
        
        assert constraint.validate(0) is not None
        assert constraint.validate(1) is None
    
    def test_chained_constraints(self):
        """Test multiple constraints chained."""
        constraint = FieldConstraint('test') \
            .type_check(int) \
            .range_check(0, 100)
        
        assert constraint.validate(50) is None
        assert constraint.validate('50') is not None  # Wrong type
        assert constraint.validate(150) is not None  # Out of range
    
    def test_required_field_missing(self):
        """Test required field validation."""
        constraint = FieldConstraint('test', required=True)
        result = constraint.validate(None)
        assert result is not None
        assert any('required' in err.lower() for err in result)
    
    def test_required_field_empty_string(self):
        """Test required field with empty string."""
        constraint = FieldConstraint('test', required=True)
        result = constraint.validate('')
        assert result is not None


class TestValidationResult:
    """Tests for validation result."""
    
    def test_add_error(self):
        """Test adding error to result."""
        result = ValidationResult(is_valid=True)
        result.add_error('field', 'error message', 'type')
        
        assert not result.is_valid
        assert len(result.errors) == 1
        assert result.errors[0].field == 'field'
    
    def test_add_warning(self):
        """Test adding warning to result."""
        result = ValidationResult(is_valid=True)
        result.add_warning('field', 'warning message')
        
        assert result.is_valid  # Warnings don't invalidate
        assert len(result.warnings) == 1
    
    def test_all_issues(self):
        """Test getting all issues."""
        result = ValidationResult(is_valid=True)
        result.add_error('f1', 'error', 'type')
        result.add_warning('f2', 'warning')
        
        all_issues = result.all_issues()
        assert len(all_issues) == 2
    
    def test_summary_valid(self):
        """Test summary for valid config."""
        result = ValidationResult(is_valid=True)
        assert '✓' in result.summary()
        assert 'valid' in result.summary().lower()
    
    def test_summary_invalid(self):
        """Test summary for invalid config."""
        result = ValidationResult(is_valid=True)
        result.add_error('field', 'error', 'type')
        assert '✗' in result.summary()


class TestConfigValidator:
    """Tests for base config validator."""
    
    def test_require_field(self):
        """Test requiring a field."""
        validator = ConfigValidator()
        validator.require_field('domain', str)
        
        result = validator.validate({})
        assert not result.is_valid
        assert any(e.field == 'domain' for e in result.errors)
    
    def test_optional_field_missing(self):
        """Test optional field can be missing."""
        validator = ConfigValidator()
        validator.optional_field('debug').type_check(bool)
        
        result = validator.validate({})
        assert result.is_valid
    
    def test_optional_field_invalid_type(self):
        """Test optional field type check."""
        validator = ConfigValidator()
        validator.optional_field('debug').type_check(bool)
        
        result = validator.validate({'debug': 'not_bool'})
        assert not result.is_valid
    
    def test_dependency_met(self):
        """Test dependency is satisfied."""
        validator = ConfigValidator()
        validator.require_field('max_rel', int)
        validator.add_dependency(
            'max_rel',
            'max_ent',
            lambda cfg: 'max_ent' in cfg and cfg['max_ent'] > 0
        )
        
        result = validator.validate({'max_rel': 100, 'max_ent': 10})
        assert result.is_valid
    
    def test_dependency_not_met(self):
        """Test dependency is not satisfied."""
        validator = ConfigValidator()
        validator.add_dependency(
            'max_rel',
            'max_ent',
            lambda cfg: 'max_ent' in cfg
        )
        
        result = validator.validate({'max_rel': 100})
        assert not result.is_valid
        assert any(e.error_type == 'dependency' for e in result.errors)


class TestExtractionConfigValidator:
    """Tests for ExtractionConfig validator."""
    
    def test_valid_extraction_config(self):
        """Test validating valid extraction config."""
        validator = ExtractionConfigValidator()
        config = {
            'confidence_threshold': 0.7,
            'max_entities': 100,
            'max_relationships': 500,
            'window_size': 10,
        }
        
        result = validator.validate(config)
        assert result.is_valid
    
    def test_invalid_confidence_threshold(self):
        """Test invalid confidence threshold."""
        validator = ExtractionConfigValidator()
        config = {'confidence_threshold': 1.5}
        
        result = validator.validate(config)
        assert not result.is_valid
        assert any(e.field == 'confidence_threshold' for e in result.errors)
    
    def test_invalid_max_entities(self):
        """Test invalid max_entities."""
        validator = ExtractionConfigValidator()
        config = {'max_entities': -1}
        
        result = validator.validate(config)
        assert not result.is_valid
    
    def test_invalid_window_size(self):
        """Test invalid window_size."""
        validator = ExtractionConfigValidator()
        config = {'window_size': 0}
        
        result = validator.validate(config)
        assert not result.is_valid
    
    def test_invalid_stopwords_type(self):
        """Test invalid stopwords type."""
        validator = ExtractionConfigValidator()
        config = {'stopwords': 'not a list'}
        
        result = validator.validate(config)
        assert not result.is_valid
    
    def test_invalid_stopwords_items(self):
        """Test invalid stopwords items."""
        validator = ExtractionConfigValidator()
        config = {'stopwords': ['hello', 123]}
        
        result = validator.validate(config)
        assert not result.is_valid
    
    def test_valid_domain_vocab(self):
        """Test valid domain vocab."""
        validator = ExtractionConfigValidator()
        config = {
            'domain_vocab': {
                'legal': ['plaintiff', 'defendant', 'court'],
                'medical': ['diagnosis', 'treatment', 'patient']
            }
        }
        
        result = validator.validate(config)
        assert result.is_valid
    
    def test_invalid_domain_vocab_structure(self):
        """Test invalid domain vocab structure."""
        validator = ExtractionConfigValidator()
        config = {'domain_vocab': 'not a dict'}
        
        result = validator.validate(config)
        assert not result.is_valid


class TestOptimizerConfigValidator:
    """Tests for optimizer config validator."""
    
    def test_requires_domain(self):
        """Test domain field is required."""
        validator = OptimizerConfigValidator()
        result = validator.validate({})
        
        assert not result.is_valid
        assert any(e.field == 'domain' for e in result.errors)
    
    def test_valid_optimizer_config(self):
        """Test valid optimizer config."""
        validator = OptimizerConfigValidator()
        config = {
            'domain': 'legal',
            'max_iterations': 100,
            'convergence_threshold': 0.95,
            'learning_rate': 0.01,
            'batch_size': 32,
        }
        
        result = validator.validate(config)
        assert result.is_valid
    
    def test_invalid_max_iterations(self):
        """Test invalid max_iterations."""
        validator = OptimizerConfigValidator()
        config = {
            'domain': 'legal',
            'max_iterations': 0  # Must be > 0
        }
        
        result = validator.validate(config)
        assert not result.is_valid
    
    def test_invalid_learning_rate(self):
        """Test invalid learning_rate."""
        validator = OptimizerConfigValidator()
        config = {
            'domain': 'legal',
            'learning_rate': -0.1  # Must be > 0
        }
        
        result = validator.validate(config)
        assert not result.is_valid


class TestConfigIssueDetection:
    """Tests for configuration issue detection."""
    
    def test_high_confidence_threshold_warning(self):
        """Test detection of high confidence threshold."""
        config = {'confidence_threshold': 0.99}
        
        issues = detect_configuration_issues(config)
        
        assert len(issues) > 0
        assert any('confidence' in i['field'].lower() for i in issues)
    
    def test_unrealistic_relationships_limit(self):
        """Test detection of unrealistic relationships limit."""
        config = {
            'max_entities': 10,
            'max_relationships': 1000  # 10^2 = 100, so 1000 is unrealistic
        }
        
        issues = detect_configuration_issues(config)
        
        assert len(issues) > 0
        assert any('relationships' in i['field'].lower() for i in issues)
    
    def test_small_window_size_warning(self):
        """Test detection of small window size."""
        config = {'window_size': 2}
        
        issues = detect_configuration_issues(config)
        
        assert len(issues) > 0
        assert any('window' in i['issue'].lower() for i in issues)
    
    def test_reasonable_config_no_issues(self):
        """Test reasonable config has no issues."""
        config = {
            'confidence_threshold': 0.7,
            'max_entities': 100,
            'max_relationships': 500,
            'window_size': 10,
        }
        
        issues = detect_configuration_issues(config)
        
        assert len(issues) == 0


class TestConfigMerging:
    """Tests for configuration merging with defaults."""
    
    def test_merge_with_defaults(self):
        """Test merging config with defaults."""
        defaults = {
            'confidence_threshold': 0.5,
            'max_entities': 100,
            'window_size': 5,
        }
        user_config = {
            'confidence_threshold': 0.7,
            'max_entities': 200,
        }
        
        merged = merge_config_with_defaults(user_config, defaults)
        
        assert merged['confidence_threshold'] == 0.7  # User value
        assert merged['max_entities'] == 200  # User value
        assert merged['window_size'] == 5  # Default value
    
    def test_merge_user_overrides_all(self):
        """Test user config completely overrides defaults."""
        defaults = {'a': 1, 'b': 2, 'c': 3}
        user_config = {'a': 10, 'b': 20}
        
        merged = merge_config_with_defaults(user_config, defaults)
        
        assert merged['a'] == 10
        assert merged['b'] == 20
        assert merged['c'] == 3
    
    def test_merge_doesnt_modify_defaults(self):
        """Test merge doesn't modify original defaults."""
        defaults = {'a': 1, 'b': 2}
        user_config = {'c': 3}
        
        merged = merge_config_with_defaults(user_config, defaults)
        
        # Defaults should not have 'c'
        assert 'c' not in defaults
        assert merged['c'] == 3


class TestErrorMessages:
    """Tests for helpful error messages."""
    
    def test_type_error_message(self):
        """Test type error message is helpful."""
        constraint = FieldConstraint('config_param').type_check(int)
        result = constraint.validate('not_an_int')
        
        assert result is not None
        assert 'int' in result[0]
        assert 'str' in result[0]
    
    def test_range_error_message(self):
        """Test range error message is helpful."""
        constraint = FieldConstraint('timeout').range_check(1, 3600)
        result = constraint.validate(5000)
        
        assert result is not None
        assert '3600' in result[0]
    
    def test_required_field_error_message(self):
        """Test required field error message."""
        constraint = FieldConstraint('domain', required=True)
        result = constraint.validate(None)
        
        assert result is not None
        assert 'required' in result[0].lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
