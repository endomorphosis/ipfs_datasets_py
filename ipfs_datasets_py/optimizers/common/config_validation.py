"""
Configuration Validation Schema - Batch 236 [arch].

Centralized configuration validation for all optimizer configuration classes.
Provides consistent validation rules, error messages, and type checking across
OptimizerConfig, ExtractionConfig, and other configuration objects.

Key Features:
    - Declarative validation rules
    - Type checking and range validation
    - Custom validators for complex rules
    - Detailed error messages with field names
    - Composable validation chains
    - Zero external dependencies (pure Python)

Usage:
    >>> from optimizers.common.config_validation import ConfigValidator, Rule
    >>> 
    >>> validator = ConfigValidator([
    ...     Rule("confidence_threshold", float, range_check=(0.0, 1.0)),
    ...     Rule("max_entities", int, min_value=0),
    ... ])
    >>> 
    >>> errors = validator.validate(config_dict)
    >>> if errors:
    ...     print(f"Validation failed: {errors}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union

logger = logging.getLogger(__name__)


# ============================================================================
# Validation Rule Definition
# ============================================================================


@dataclass
class ValidationRule:
    """Single validation rule for a configuration field.
    
    Attributes:
        field_name: Name of configuration field
        expected_type: Expected Python type (or tuple of types)
        required: Whether field is required
        min_value: Minimum value for numeric fields
        max_value: Maximum value for numeric fields
        range_check: Tuple of (min, max) for range validation
        allowed_values: Set of allowed discrete values
        custom_validator: Custom validation function(value) -> (bool, str)
        error_message: Custom error message template
    """
    
    field_name: str
    expected_type: Optional[Union[Type, Tuple[Type, ...]]] = None
    required: bool = True
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    range_check: Optional[Tuple[Union[int, float], Union[int, float]]] = None
    allowed_values: Optional[Set[Any]] = None
    custom_validator: Optional[Callable[[Any], Tuple[bool, str]]] = None
    error_message: Optional[str] = None
    
    def validate(self, value: Any) -> List[str]:
        """Validate value against this rule.
        
        Args:
            value: Value to validate
            
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        
        # Type checking
        if self.expected_type is not None and value is not None:
            if not isinstance(value, self.expected_type):
                type_name = self._format_type(self.expected_type)
                errors.append(
                    f"Field '{self.field_name}' must be {type_name}, "
                    f"got {type(value).__name__}"
                )
        
        # Min value check
        if self.min_value is not None and value is not None:
            if not isinstance(value, (int, float)):
                errors.append(
                    f"Field '{self.field_name}' cannot check min_value "
                    f"on non-numeric type {type(value).__name__}"
                )
            elif value < self.min_value:
                errors.append(
                    f"Field '{self.field_name}' must be >= {self.min_value}, "
                    f"got {value}"
                )
        
        # Max value check
        if self.max_value is not None and value is not None:
            if not isinstance(value, (int, float)):
                errors.append(
                    f"Field '{self.field_name}' cannot check max_value "
                    f"on non-numeric type {type(value).__name__}"
                )
            elif value > self.max_value:
                errors.append(
                    f"Field '{self.field_name}' must be <= {self.max_value}, "
                    f"got {value}"
                )
        
        # Range check
        if self.range_check is not None and value is not None:
            min_val, max_val = self.range_check
            if not isinstance(value, (int, float)):
                errors.append(
                    f"Field '{self.field_name}' cannot check range "
                    f"on non-numeric type {type(value).__name__}"
                )
            elif not (min_val <= value <= max_val):
                errors.append(
                    f"Field '{self.field_name}' must be in range "
                    f"[{min_val}, {max_val}], got {value}"
                )
        
        # Allowed values check
        if self.allowed_values is not None and value is not None:
            if value not in self.allowed_values:
                allowed_str = ", ".join(str(v) for v in sorted(self.allowed_values))
                errors.append(
                    f"Field '{self.field_name}' must be one of [{allowed_str}], "
                    f"got {value}"
                )
        
        # Custom validator
        if self.custom_validator is not None and value is not None:
            is_valid, error_msg = self.custom_validator(value)
            if not is_valid:
                errors.append(
                    f"Field '{self.field_name}' failed validation: {error_msg}"
                )
        
        # Use custom error message if provided and errors exist
        if self.error_message and errors:
            return [self.error_message.format(value=value, field=self.field_name)]
        
        return errors
    
    @staticmethod
    def _format_type(expected_type: Union[Type, Tuple[Type, ...]]) -> str:
        """Format type for error messages.
        
        Args:
            expected_type: Type or tuple of types
            
        Returns:
            Human-readable type string
        """
        if isinstance(expected_type, tuple):
            type_names = [t.__name__ for t in expected_type]
            return " or ".join(type_names)
        return expected_type.__name__


# ============================================================================
# Configuration Validator
# ============================================================================


class ConfigValidator:
    """Validator for configuration dictionaries.
    
    Validates configuration against a set of validation rules,
    providing detailed error messages for failed validations.
    """
    
    def __init__(self, rules: List[ValidationRule]):
        """Initialize validator with rules.
        
        Args:
            rules: List of validation rules to apply
        """
        self.rules = {rule.field_name: rule for rule in rules}
        self._validate_rules()
    
    def _validate_rules(self):
        """Validate that rules themselves are consistent."""
        for field_name, rule in self.rules.items():
            # Check for conflicting min/max
            if rule.min_value is not None and rule.max_value is not None:
                if rule.min_value > rule.max_value:
                    raise ValueError(
                        f"Rule for '{field_name}': min_value ({rule.min_value}) "
                        f"> max_value ({rule.max_value})"
                    )
            
            # Check for conflicting range and min/max
            if rule.range_check is not None:
                min_val, max_val = rule.range_check
                if rule.min_value is not None and rule.min_value != min_val:
                    logger.warning(
                        f"Rule for '{field_name}': range_check overrides min_value"
                    )
                if rule.max_value is not None and rule.max_value != max_val:
                    logger.warning(
                        f"Rule for '{field_name}': range_check overrides max_value"
                    )
    
    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate configuration dictionary.
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        
        # Check required fields
        for field_name, rule in self.rules.items():
            if rule.required and field_name not in config:
                errors.append(f"Required field '{field_name}' is missing")
        
        # Validate present fields
        for field_name, value in config.items():
            if field_name in self.rules:
                rule_errors = self.rules[field_name].validate(value)
                errors.extend(rule_errors)
            else:
                # Unknown field - warning but not error
                logger.debug(f"Unknown field '{field_name}' in configuration")
        
        return errors
    
    def validate_partial(self, config: Dict[str, Any]) -> List[str]:
        """Validate configuration, ignoring missing fields.
        
        Useful for partial configuration updates.
        
        Args:
            config: Partial configuration dictionary
            
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        
        # Only validate present fields, ignoring required checks
        for field_name, value in config.items():
            if field_name in self.rules:
                rule_errors = self.rules[field_name].validate(value)
                errors.extend(rule_errors)
        
        return errors
    
    def is_valid(self, config: Dict[str, Any]) -> bool:
        """Check if configuration is valid.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if valid, False otherwise
        """
        return len(self.validate(config)) == 0
    
    def add_rule(self, rule: ValidationRule):
        """Add validation rule dynamically.
        
        Args:
            rule: Validation rule to add
        """
        self.rules[rule.field_name] = rule
    
    def remove_rule(self, field_name: str):
        """Remove validation rule.
        
        Args:
            field_name: Field to remove rule for
        """
        self.rules.pop(field_name, None)


# ============================================================================
# Pre-built Validators for Common Config Types
# ============================================================================


def create_extraction_config_validator() -> ConfigValidator:
    """Create validator for ExtractionConfig.
    
    Returns:
        Configured ConfigValidator for extraction configs
    """
    rules = [
        ValidationRule(
            "confidence_threshold",
            expected_type=float,
            range_check=(0.0, 1.0),
            required=False,
        ),
        ValidationRule(
            "max_confidence",
            expected_type=float,
            range_check=(0.0, 1.0),
            required=False,
        ),
        ValidationRule(
            "llm_fallback_threshold",
            expected_type=float,
            range_check=(0.0, 1.0),
            required=False,
        ),
        ValidationRule(
            "max_entities",
            expected_type=int,
            min_value=0,
            required=False,
        ),
        ValidationRule(
            "max_relationships",
            expected_type=int,
            min_value=0,
            required=False,
        ),
        ValidationRule(
            "min_entity_length",
            expected_type=int,
            min_value=1,
            required=False,
        ),
        ValidationRule(
            "window_size",
            expected_type=int,
            min_value=1,
            required=False,
        ),
        ValidationRule(
            "include_properties",
            expected_type=bool,
            required=False,
        ),
        ValidationRule(
            "stopwords",
            expected_type=(list, set),
            required=False,
        ),
        ValidationRule(
            "domain_vocab",
            expected_type=(list, set),
            required=False,
        ),
        ValidationRule(
            "allowed_entity_types",
            expected_type=(list, set),
            required=False,
        ),
        ValidationRule(
            "custom_rules",
            expected_type=list,
            required=False,
        ),
    ]
    
    return ConfigValidator(rules)


def create_optimizer_config_validator() -> ConfigValidator:
    """Create validator for OptimizerConfig.
    
    Returns:
        Configured ConfigValidator for optimizer configs
    """
    rules = [
        ValidationRule(
            "max_rounds",
            expected_type=int,
            min_value=1,
            required=True,
        ),
        ValidationRule(
            "convergence_threshold",
            expected_type=float,
            range_check=(0.0, 1.0),
            required=True,
        ),
        ValidationRule(
            "min_improvement",
            expected_type=float,
            min_value=0.0,
            required=False,
        ),
        ValidationRule(
            "timeout_seconds",
            expected_type=(int, float),
            min_value=0,
            required=False,
        ),
        ValidationRule(
            "enable_caching",
            expected_type=bool,
            required=False,
        ),
        ValidationRule(
            "log_level",
            expected_type=str,
            allowed_values={"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"},
            required=False,
        ),
    ]
    
    return ConfigValidator(rules)


# ============================================================================
# Custom Validators
# ============================================================================


def validate_threshold_relationship(config: Dict[str, Any]) -> List[str]:
    """Validate that confidence_threshold < max_confidence.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        List of error messages
    """
    errors = []
    
    if "confidence_threshold" in config and "max_confidence" in config:
        conf_thresh = config["confidence_threshold"]
        max_conf = config["max_confidence"]
        
        if conf_thresh > max_conf:
            errors.append(
                f"confidence_threshold ({conf_thresh}) must be <= "
                f"max_confidence ({max_conf})"
            )
    
    return errors


def validate_entity_limits(config: Dict[str, Any]) -> List[str]:
    """Validate entity count limits are reasonable.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        List of error messages
    """
    errors = []
    
    if "max_entities" in config:
        max_entities = config["max_entities"]
        if max_entities > 100000:
            errors.append(
                f"max_entities ({max_entities}) exceeds recommended limit (100,000)"
            )
    
    if "max_relationships" in config:
        max_rels = config["max_relationships"]
        if max_rels > 1000000:
            errors.append(
                f"max_relationships ({max_rels}) exceeds recommended limit (1,000,000)"
            )
    
    return errors


# ============================================================================
# Composite Validator
# ============================================================================


class CompositeValidator:
    """Validator that combines multiple validators and cross-field checks."""
    
    def __init__(
        self,
        field_validator: ConfigValidator,
        cross_field_validators: Optional[List[Callable[[Dict[str, Any]], List[str]]]] = None,
    ):
        """Initialize composite validator.
        
        Args:
            field_validator: Validator for individual fields
            cross_field_validators: List of cross-field validation functions
        """
        self.field_validator = field_validator
        self.cross_field_validators = cross_field_validators or []
    
    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate configuration with field and cross-field checks.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            List of error messages
        """
        # Field validation
        errors = self.field_validator.validate(config)
        
        # Cross-field validation
        for validator_func in self.cross_field_validators:
            cross_errors = validator_func(config)
            errors.extend(cross_errors)
        
        return errors
    
    def is_valid(self, config: Dict[str, Any]) -> bool:
        """Check if configuration is valid.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            True if valid, False otherwise
        """
        return len(self.validate(config)) == 0


# ============================================================================
# Factory Functions
# ============================================================================


def create_comprehensive_extraction_validator() -> CompositeValidator:
    """Create comprehensive validator for ExtractionConfig.
    
    Includes field validation and cross-field checks.
    
    Returns:
        Comprehensive CompositeValidator
    """
    field_validator = create_extraction_config_validator()
    cross_field_validators = [
        validate_threshold_relationship,
        validate_entity_limits,
    ]
    
    return CompositeValidator(field_validator, cross_field_validators)


def create_comprehensive_optimizer_validator() -> CompositeValidator:
    """Create comprehensive validator for OptimizerConfig.
    
    Returns:
        Comprehensive CompositeValidator
    """
    field_validator = create_optimizer_config_validator()
    
    return CompositeValidator(field_validator, [])
