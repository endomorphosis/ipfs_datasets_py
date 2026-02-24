"""Configuration Validation Schema for GraphRAG Extraction.

Centralized configuration validation infrastructure providing:
- Field-level validation rules
- Type checking and constraints
- Domain-specific validation patterns
- Error reporting and recovery
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
import re


# ============================================================================
# Validation Rules
# ============================================================================


@dataclass
class ValidationRule:
    """Single validation rule for a configuration field."""
    
    name: str
    """Rule identifier (e.g., 'range', 'type', 'pattern')"""
    
    condition: Callable[[Any], bool]
    """Function returning True if value passes validation"""
    
    message: str
    """Error message if validation fails"""
    
    optional: bool = False
    """Whether this rule applies only to non-None values"""


class ValidationRuleSet:
    """Collection of validation rules for a field."""
    
    def __init__(self, field_name: str, field_type: type):
        self.field_name = field_name
        self.field_type = field_type
        self.rules: List[ValidationRule] = []
    
    def add_rule(self, rule: ValidationRule) -> ValidationRuleSet:
        """Add a validation rule and return self for chaining."""
        self.rules.append(rule)
        return self
    
    def add_type_check(self, allowed_types: Union[type, Tuple[type, ...]]) -> ValidationRuleSet:
        """Add type validation rule."""
        if isinstance(allowed_types, type):
            allowed_types = (allowed_types,)
        
        rule = ValidationRule(
            name="type",
            condition=lambda x: x is None or isinstance(x, allowed_types),
            message=f"{self.field_name} must be of type {allowed_types}, got {{type}}"
        )
        return self.add_rule(rule)
    
    def add_range(self, min_val: float = None, max_val: float = None) -> ValidationRuleSet:
        """Add numeric range validation."""
        def check_range(x):
            if x is None:
                return True
            try:
                if min_val is not None and x < min_val:
                    return False
                if max_val is not None and x > max_val:
                    return False
                return True
            except TypeError:
                return False
        
        bounds = []
        if min_val is not None:
            bounds.append(f">= {min_val}")
        if max_val is not None:
            bounds.append(f"<= {max_val}")
        
        rule = ValidationRule(
            name="range",
            condition=check_range,
            message=f"{self.field_name} must be {' and '.join(bounds)}, got {{value}}"
        )
        return self.add_rule(rule)
    
    def add_pattern(self, pattern: str) -> ValidationRuleSet:
        """Add regex pattern validation."""
        regex = re.compile(pattern)
        rule = ValidationRule(
            name="pattern",
            condition=lambda x: x is None or bool(regex.match(str(x))),
            message=f"{self.field_name} must match pattern {pattern}, got {{value}}"
        )
        return self.add_rule(rule)
    
    def add_custom(self, name: str, condition: Callable, message: str) -> ValidationRuleSet:
        """Add custom validation rule."""
        rule = ValidationRule(name=name, condition=condition, message=message)
        return self.add_rule(rule)
    
    def add_collection_type(self, element_type: type) -> ValidationRuleSet:
        """Validate collection elements are of specific type."""
        return self.add_custom(
            name="collection_type",
            condition=lambda x: x is None or (isinstance(x, (list, set, tuple)) and 
                                             all(isinstance(item, element_type) for item in x)),
            message=f"All items in {self.field_name} must be {element_type.__name__}"
        )
    
    def validate(self, value: Any) -> Tuple[bool, List[str]]:
        """Validate value against all rules. Returns (is_valid, error_messages)."""
        errors = []
        for rule in self.rules:
            if rule.optional and value is None:
                continue
            if not rule.condition(value):
                msg = rule.message.format(value=value, type=type(value).__name__)
                errors.append(msg)
        return len(errors) == 0, errors


# ============================================================================
# Extraction Config Validation Schema
# ============================================================================


class ExtractionConfigSchema:
    """Schema for validating ExtractionConfig fields."""
    
    def __init__(self):
        self.fields: Dict[str, ValidationRuleSet] = {}
        self._setup_rules()
    
    def _setup_rules(self):
        """Setup validation rules for all ExtractionConfig fields."""
        
        # confidence: float [0, 1]
        confidence = ValidationRuleSet("confidence", float)
        confidence.add_type_check(float).add_range(0.0, 1.0)
        self.fields["confidence"] = confidence
        
        # max_confidence: float [0, 1]
        max_conf = ValidationRuleSet("max_confidence", float)
        max_conf.add_type_check(float).add_range(0.0, 1.0)
        self.fields["max_confidence"] = max_conf
        
        # llm_fallback_threshold: float [0, 1]
        llm_fb = ValidationRuleSet("llm_fallback_threshold", float)
        llm_fb.add_type_check(float).add_range(0.0, 1.0)
        self.fields["llm_fallback_threshold"] = llm_fb
        
        # max_entities: int >= 0
        max_ent = ValidationRuleSet("max_entities", int)
        max_ent.add_type_check(int).add_range(min_val=0)
        self.fields["max_entities"] = max_ent
        
        # max_relationships: int >= 0
        max_rel = ValidationRuleSet("max_relationships", int)
        max_rel.add_type_check(int).add_range(min_val=0)
        self.fields["max_relationships"] = max_rel
        
        # min_entity_length: int > 0
        min_len = ValidationRuleSet("min_entity_length", int)
        min_len.add_type_check(int).add_range(min_val=1)
        self.fields["min_entity_length"] = min_len
        
        # window_size: int > 0
        window = ValidationRuleSet("window_size", int)
        window.add_type_check(int).add_range(min_val=1)
        self.fields["window_size"] = window

        # sentence_window: int >= 0 (0 disables sentence limiting)
        sentence_window = ValidationRuleSet("sentence_window", int)
        sentence_window.add_type_check(int).add_range(min_val=0)
        self.fields["sentence_window"] = sentence_window
        
        # enable_parallel_inference: bool (enables parallel relationship inference)
        parallel_enabled = ValidationRuleSet("enable_parallel_inference", bool)
        parallel_enabled.add_type_check(bool)
        self.fields["enable_parallel_inference"] = parallel_enabled
        
        # max_workers: int >= 1 (number of threads for parallel inference)
        max_workers = ValidationRuleSet("max_workers", int)
        max_workers.add_type_check(int).add_range(min_val=1)
        self.fields["max_workers"] = max_workers
        
        # stopwords: List[str]
        stopwords = ValidationRuleSet("stopwords", list)
        stopwords.add_type_check((list, set, tuple))
        stopwords.add_collection_type(str)
        self.fields["stopwords"] = stopwords
        
        # allowed_entity_types: List[str]
        types = ValidationRuleSet("allowed_entity_types", list)
        types.add_type_check((list, set, tuple))
        types.add_collection_type(str)
        self.fields["allowed_entity_types"] = types
        
        # domain_vocab: Dict[str, Any]
        vocab = ValidationRuleSet("domain_vocab", dict)
        vocab.add_type_check(dict)
        self.fields["domain_vocab"] = vocab
        
        # custom_rules: List[str]
        rules = ValidationRuleSet("custom_rules", list)
        rules.add_type_check((list, set, tuple))
        rules.add_collection_type(str)
        self.fields["custom_rules"] = rules
        
        # include_properties: bool
        props = ValidationRuleSet("include_properties", bool)
        props.add_type_check(bool)
        self.fields["include_properties"] = props
    
    def validate(self, config_dict: Dict[str, Any]) -> Tuple[bool, Dict[str, List[str]]]:
        """
        Validate entire config dict. Returns (is_valid, error_dict).
        
        Args:
            config_dict: Configuration dictionary to validate
        
        Returns:
            (is_valid: bool, errors: Dict[field_name -> List[error_messages]])
        """
        errors = {}
        
        for field_name, rule_set in self.fields.items():
            value = config_dict.get(field_name)
            is_valid, field_errors = rule_set.validate(value)
            if not is_valid:
                errors[field_name] = field_errors
        
        # Check cross-field constraints
        cross_errors = self._validate_cross_field_constraints(config_dict)
        if cross_errors:
            errors.update(cross_errors)
        
        return len(errors) == 0, errors
    
    def _validate_cross_field_constraints(self, config_dict: Dict[str, Any]) -> Dict[str, List[str]]:
        """Validate constraints across multiple fields."""
        errors = {}
        
        # confidence < max_confidence
        conf = config_dict.get("confidence", 0.5)
        max_conf = config_dict.get("max_confidence", 0.95)
        try:
            if conf >= max_conf:
                errors["confidence"] = [f"confidence ({conf}) must be less than max_confidence ({max_conf})"]
        except TypeError:
            # Skip comparison if types are incompatible (field-level validation will catch)
            pass
        
        # min_entity_length < max_entities (if both specified)
        min_len = config_dict.get("min_entity_length")
        max_ent = config_dict.get("max_entities")
        if min_len and max_ent and min_len * 10 > max_ent:
            errors["min_entity_length"] = [
                f"min_entity_length ({min_len}) * 10 > max_entities ({max_ent}) may be too restrictive"
            ]
        
        return errors
    
    def get_field_rule(self, field_name: str) -> Optional[ValidationRuleSet]:
        """Get validation rule set for a specific field."""
        return self.fields.get(field_name)


# ============================================================================
# Configuration Error Handling
# ============================================================================


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    
    def __init__(self, field_name: str, errors: List[str]):
        self.field_name = field_name
        self.errors = errors
        message = f"Validation error in {field_name}: {'; '.join(errors)}"
        super().__init__(message)


class ConfigValidator:
    """High-level configuration validator with error recovery."""
    
    def __init__(self, schema: Optional[ExtractionConfigSchema] = None):
        self.schema = schema or ExtractionConfigSchema()
    
    def validate_and_fix(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate config and attempt to fix common issues.
        
        Returns:
            Corrected config dict
        """
        fixed = dict(config_dict)
        
        # Auto-fix common issues
        if "confidence" in fixed and "max_confidence" in fixed:
            if fixed["confidence"] >= fixed["max_confidence"]:
                fixed["max_confidence"] = min(1.0, fixed["confidence"] + 0.1)
        
        return fixed
    
    def validate_strict(self, config_dict: Dict[str, Any]) -> bool:
        """Validate config, raising exception on first error."""
        is_valid, errors = self.schema.validate(config_dict)
        
        if not is_valid:
            # Get first error
            for field, field_errors in errors.items():
                raise ConfigValidationError(field, field_errors)
        
        return True
