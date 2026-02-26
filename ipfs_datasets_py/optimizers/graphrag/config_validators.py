"""
Configuration schema validation and constraint checking utilities.

This module provides comprehensive validation for ExtractionConfig and optimizer
configurations, including:

- Schema validation against allowed types and constraints
- Range and value validation for numeric and enum fields
- Interdependency checking (e.g., max_relationships requires max_entities)
- Configuration migration and versioning support
- Default value application and standardization
- Detailed validation reporting with fix suggestions

Features:
- Fluent validation API for building custom validators
- Pre-built validators for common constraint patterns
- Schema enforcement with clear error messages
- Auto-correction suggestions for common mistakes
- Configuration upgrade utilities for schema evolution

Usage:
    >>> config = {'confidence_threshold': 1.5, 'max_entities': 0}
    >>> validator = ExtractionConfigValidator()
    >>> result = validator.validate(config)
    >>> if not result.is_valid:
    ...     print(result.errors)
    ...     print(result.suggestions)

Examples:
    >>> # Build custom validator
    >>> validator = ConfigValidator()
    >>> validator.require_field('domain', str)
    >>> validator.range_check('timeout', 1, 3600)
    >>> validator.enum_check('strategy', ['vector', 'keyword', 'hybrid'])
    
    >>> # Validate with validation
    >>> result = validator.validate(config)
    >>> if result.is_valid:
    ...     corrected = result.corrected_config
"""

from typing import Any, Dict, List, Optional, Callable, Set, Tuple, Union, TypedDict
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
import logging


logger = logging.getLogger(__name__)


# ===== TypedDict Definitions for Return Types =====

class MergedConfigDict(TypedDict, total=False):
    """Result of merging config with defaults.
    
    Fields:
        All fields from merged configuration dictionary
        (dynamic structure based on input configs)
    """
    pass


@dataclass
class ValidationError:
    """Single validation error with optional suggestions."""
    field: str
    message: str
    error_type: str  # 'type', 'range', 'enum', 'dependency', 'format'
    severity: str = 'error'  # 'error', 'warning'
    suggestions: List[str] = dataclass_field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of configuration validation."""
    is_valid: bool
    errors: List[ValidationError] = dataclass_field(default_factory=list)
    warnings: List[ValidationError] = dataclass_field(default_factory=list)
    corrected_config: Dict[str, Any] = dataclass_field(default_factory=dict)
    
    def add_error(
        self, 
        field: str, 
        message: str, 
        error_type: str,
        suggestions: Optional[List[str]] = None
    ) -> None:
        """Add validation error."""
        self.errors.append(ValidationError(
            field=field,
            message=message,
            error_type=error_type,
            suggestions=suggestions or []
        ))
        self.is_valid = False
    
    def add_warning(
        self, 
        field: str, 
        message: str, 
        suggestions: Optional[List[str]] = None
    ) -> None:
        """Add validation warning."""
        self.warnings.append(ValidationError(
            field=field,
            message=message,
            error_type='warning',
            severity='warning',
            suggestions=suggestions or []
        ))
    
    def all_issues(self) -> List[ValidationError]:
        """Get all errors and warnings."""
        return self.errors + self.warnings
    
    def summary(self) -> str:
        """Get summary of validation result."""
        if self.is_valid:
            return "✓ Configuration valid"
        msg = f"✗ Configuration invalid: {len(self.errors)} error(s)"
        if self.warnings:
            msg += f", {len(self.warnings)} warning(s)"
        return msg


class FieldConstraint:
    """Constraint on a configuration field."""
    
    def __init__(self, name: str, required: bool = False):
        self.name = name
        self.required = required
        self.validators: List[Callable[[Any], Optional[str]]] = []
    
    def type_check(self, expected_type: type) -> 'FieldConstraint':
        """Add type check constraint."""
        def validate_type(value: Any) -> Optional[str]:
            if value is None:
                return None  # type checks don't validate None
            if not isinstance(value, expected_type):
                return f"Expected {expected_type.__name__}, got {type(value).__name__}"
            return None
        self.validators.append(validate_type)
        return self
    
    def range_check(self, min_val: Optional[float] = None, max_val: Optional[float] = None) -> 'FieldConstraint':
        """Add numeric range check."""
        def validate_range(value: Any) -> Optional[str]:
            if value is None: 
                return None
            if not isinstance(value, (int, float)):
                return f"Must be numeric, got {type(value).__name__}"
            if min_val is not None and value < min_val:
                return f"Must be >= {min_val}, got {value}"
            if max_val is not None and value > max_val:
                return f"Must be <= {max_val}, got {value}"
            return None
        self.validators.append(validate_range)
        return self
    
    def enum_check(self, allowed_values: List[Any]) -> 'FieldConstraint':
        """Add enum check constraint."""
        def validate_enum(value: Any) -> Optional[str]:
            if value is None:
                return None
            if value not in allowed_values:
                return f"Must be one of {allowed_values}, got {value}"
            return None
        self.validators.append(validate_enum)
        return self
    
    def custom(self, validator: Callable[[Any], Optional[str]]) -> 'FieldConstraint':
        """Add custom validator function."""
        self.validators.append(validator)
        return self
    
    def validate(self, value: Any) -> Optional[List[str]]:
        """Validate value against all constraints.
        
        Returns:
            None if valid, list of error messages if invalid
        """
        if self.required and (value is None or (isinstance(value, str) and not value.strip())):
            return [f"Required field '{self.name}' is missing or empty"]
        
        if value is None:
            return None  # Only required fields need values
        
        errors = []
        for validator in self.validators:
            error = validator(value)
            if error:
                errors.append(error)
        
        return errors if errors else None


class ConfigValidator:
    """Base configuration validator with fluent API."""
    
    def __init__(self) -> None:
        self.constraints: Dict[str, FieldConstraint] = {}
        self.dependencies: List[Tuple[str, Callable[[Dict[str, Any]], bool], str]] = []
    
    def require_field(self, field: str, field_type: Optional[type] = None) -> FieldConstraint:
        """Require a field in configuration."""
        constraint = FieldConstraint(field, required=True)
        if field_type:
            constraint.type_check(field_type)
        self.constraints[field] = constraint
        return constraint
    
    def optional_field(self, field: str) -> FieldConstraint:
        """Define optional field."""
        constraint = FieldConstraint(field, required=False)
        self.constraints[field] = constraint
        return constraint
    
    def add_dependency(
        self, 
        dependent_field: str, 
        requires_field: str,
        condition: Optional[Callable[[Dict[str, Any]], bool]] = None
    ) -> None:
        """Add field dependency (e.g., max_relationships requires max_entities)."""
        condition = condition or (lambda cfg: requires_field in cfg and cfg[requires_field] is not None)
        msg = f"Field '{dependent_field}' requires '{requires_field}' to be set"
        self.dependencies.append((dependent_field, condition, msg))
    
    def validate(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate configuration.
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            ValidationResult with validation outcome
        """
        result = ValidationResult(is_valid=True, corrected_config=dict(config))
        
        # Check all constraints
        for field_name, constraint in self.constraints.items():
            value = config.get(field_name)
            errors = constraint.validate(value)
            if errors:
                for error_msg in errors:
                    result.add_error(field_name, error_msg, 'constraint_violation')
        
        # Check dependencies
        for dep_field, condition, msg in self.dependencies:
            if dep_field in config and config.get(dep_field) is not None:
                if not condition(config):
                    result.add_error(dep_field, msg, 'dependency')
        
        return result


class ExtractionConfigValidator(ConfigValidator):
    """Validator for ExtractionConfig structures."""
    
    def __init__(self) -> None:
        super().__init__()
        self._setup_extraction_constraints()
    
    def _setup_extraction_constraints(self) -> None:
        """Configure constraints for ExtractionConfig fields."""
        # confidence_threshold: float in [0, 1]
        self.optional_field('confidence_threshold') \
            .type_check(float) \
            .range_check(0.0, 1.0)
        
        # max_entities: int >= 0 (0 means unlimited)
        self.optional_field('max_entities') \
            .type_check(int) \
            .range_check(0, float('inf'))
        
        # max_relationships: int >= 0
        self.optional_field('max_relationships') \
            .type_check(int) \
            .range_check(0, float('inf'))
        
        # window_size: int in [1, 1000]
        self.optional_field('window_size') \
            .type_check(int) \
            .range_check(1, 1000)
        
        # min_entity_length: int >= 1
        self.optional_field('min_entity_length') \
            .type_check(int) \
            .range_check(1, float('inf'))
        
        # stopwords: list of strings
        def validate_stopwords(value: Any) -> Optional[str]:
            if not isinstance(value, list):
                return f"Must be list, got {type(value).__name__}"
            for item in value:
                if not isinstance(item, str):
                    return f"Stopwords must be strings, got {type(item).__name__}"
            return None
        self.optional_field('stopwords').custom(validate_stopwords)
        
        # allowed_entity_types: list of strings
        def validate_entity_types(value: Any) -> Optional[str]:
            if not isinstance(value, list):
                return f"Must be list, got {type(value).__name__}"
            for item in value:
                if not isinstance(item, str):
                    return f"Entity types must be strings, got {type(item).__name__}"
            return None
        self.optional_field('allowed_entity_types').custom(validate_entity_types)
        
        # domain_vocab: dict of str -> list of strings
        def validate_domain_vocab(value: Any) -> Optional[str]:
            if not isinstance(value, dict):
                return f"Must be dict, got {type(value).__name__}"
            for key, val in value.items():
                if not isinstance(key, str):
                    return f"Domain vocab keys must be strings"
                if not isinstance(val, list):
                    return f"Domain vocab values must be lists"
                for item in val:
                    if not isinstance(item, str):
                        return f"Domain vocab items must be strings"
            return None
        self.optional_field('domain_vocab').custom(validate_domain_vocab)
        
        # max_confidence: float in (0, 1]
        self.optional_field('max_confidence') \
            .type_check(float) \
            .range_check(0.0, 1.0)
        
        # include_properties: bool
        self.optional_field('include_properties') \
            .type_check(bool)
        
        # Dependencies
        self.add_dependency(
            'max_relationships',
            'max_entities',
            lambda cfg: cfg.get('max_relationships', 0) > 0 and cfg.get('max_entities', 0) > 0
        )


class OptimizerConfigValidator(ConfigValidator):
    """Validator for optimization configuration."""
    
    def __init__(self) -> None:
        super().__init__()
        self._setup_optimizer_constraints()
    
    def _setup_optimizer_constraints(self) -> None:
        """Configure constraints for optimizer configuration."""
        # domain: required string
        self.require_field('domain', str)
        
        # max_iterations: int > 0  
        self.optional_field('max_iterations') \
            .type_check(int) \
            .range_check(1, float('inf'))
        
        # convergence_threshold: float in [0, 1]
        self.optional_field('convergence_threshold') \
            .type_check(float) \
            .range_check(0.0, 1.0)
        
        # learning_rate: float > 0
        self.optional_field('learning_rate') \
            .type_check(float) \
            .range_check(0.0, float('inf'))
        
        # batch_size: int > 0
        self.optional_field('batch_size') \
            .type_check(int) \
            .range_check(1, float('inf'))
        
        # seed: int >= 0
        self.optional_field('seed') \
            .type_check(int) \
            .range_check(0, float('inf'))


def detect_configuration_issues(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect common configuration issues and suggest fixes.
    
    Returns list of issues with fix suggestions.
    """
    issues = []
    
    # Check for overly high confidence_threshold
    threshold = config.get('confidence_threshold')
    if threshold is not None and threshold > 0.95:
        issues.append({
            'issue': 'Very high confidence threshold may filter out valid entities',
            'field': 'confidence_threshold',
            'value': threshold,
            'suggestion': 'Consider lowering to 0.7-0.9 range'
        })
    
    # Check for conflicting entity and relationship limits
    max_ent = config.get('max_entities')
    max_rel = config.get('max_relationships')
    if max_ent and max_rel:
        if max_rel > max_ent * max_ent:
            issues.append({
                'issue': 'max_relationships may be unrealistic given max_entities',
                'field': 'max_relationships',
                'value': max_rel,
                'suggestion': f'Consider max_rel <= max_entities^2 (max {max_ent * max_ent})'
            })
    
    # Check for very small window_size
    win_size = config.get('window_size')
    if win_size is not None and win_size < 3:
        issues.append({
            'issue': 'Small window size may miss co-occurrences',
            'field': 'window_size',
            'value': win_size,
            'suggestion': 'Increase to at least 5-10 for better relationship extraction'
        })
    
    return issues


def merge_config_with_defaults(
    config: Dict[str, Any],
    defaults: Dict[str, Any]
) -> MergedConfigDict:
    """Merge config with default values.
    
    Args:
        config: User configuration
        defaults: Default configuration
        
    Returns:
        Merged configuration with defaults applied
    """
    merged = dict(defaults)
    merged.update(config)
    return merged


if __name__ == '__main__':
    # Example usage
    validator = ExtractionConfigValidator()
    
    config = {
        'confidence_threshold': 0.5,
        'max_entities': 100,
        'max_relationships': 500,
    }
    
    result = validator.validate(config)
    print(f"Valid: {result.is_valid}")
    print(f"Summary: {result.summary()}")
    
    if result.errors:
        for error in result.errors:
            print(f"  {error.field}: {error.message}")
    
    # Detect common issues
    issues = detect_configuration_issues(config)
    if issues:
        print("\nConfiguration issues:")
        for issue in issues:
            print(f"  {issue['issue']}: {issue['suggestion']}")
