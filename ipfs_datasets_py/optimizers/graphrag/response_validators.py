"""
Response validators and type checkers for GraphRAG inference results.

This module provides comprehensive validation utilities for ensuring that
API responses, LLM outputs, and extraction results conform to expected schemas
and type constraints. Validators support both strict and permissive modes,
detailed error reporting, and automatic type coercion where appropriate.

Classes:
    ResponseValidator: Base validator for general response structures
    EntityExtractionValidator: Validates entity extraction outputs
    RelationshipExtractionValidator: Validates relationship extraction outputs
    CriticScoreValidator: Validates critic evaluation scores
    OntologySessionValidator: Validates complete ontology session data
    QueryPlanValidator: Validates query execution plans
    ValidationError: Exception raised for validation failures

Examples:
    >>> validator = EntityExtractionValidator()
    >>> result = validator.validate(entity_data)
    >>> if result.is_valid:
    ...     entity = result.data
    ... else:
    ...     errors = result.errors
    ...     print(f"Validation failed: {errors}")
    
    >>> # Strict mode with detailed error reporting
    >>> validator = CriticScoreValidator(strict=True, detailed_errors=True)
    >>> result = validator.validate(score_dict)
    >>> if not result.is_valid:
    ...     for error in result.detailed_errors:
    ...         print(f"{error['field']}: {error['message']}")
"""

from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union
from abc import ABC, abstractmethod
import re
import math
from dataclasses import dataclass, field
from enum import Enum


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationResult:
    """Result of a validation operation."""
    is_valid: bool
    data: Optional[Any] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    detailed_errors: List[Dict[str, Any]] = field(default_factory=list)
    
    def add_error(self, message: str, field: Optional[str] = None, code: Optional[str] = None) -> None:
        """Add an error to validation result."""
        self.errors.append(message)
        self.is_valid = False
        if field or code:
            self.detailed_errors.append({
                'severity': ValidationSeverity.ERROR.value,
                'field': field,
                'message': message,
                'code': code,
            })
    
    def add_warning(self, message: str, field: Optional[str] = None) -> None:
        """Add a warning to validation result."""
        self.warnings.append(message)
        if field:
            self.detailed_errors.append({
                'severity': ValidationSeverity.WARNING.value,
                'field': field,
                'message': message,
            })


class ResponseValidator(ABC):
    """Abstract base validator for response structures."""
    
    def __init__(
        self, 
        strict: bool = False, 
        detailed_errors: bool = False,
        allow_extra_fields: bool = True,
    ):
        """Initialize validator.
        
        Args:
            strict: If True, enforce all validations strictly
            detailed_errors: If True, collect detailed error information
            allow_extra_fields: If True, allow undeclared fields in responses
        """
        self.strict = strict
        self.detailed_errors = detailed_errors
        self.allow_extra_fields = allow_extra_fields
    
    @abstractmethod
    def validate(self, data: Any) -> ValidationResult:
        """Validate data against schema.
        
        Args:
            data: Data to validate
            
        Returns:
            ValidationResult with validation outcome
        """
        pass
    
    def _validate_type(
        self, 
        value: Any, 
        expected_type: Union[type, Tuple[type, ...]], 
        field_name: str,
        result: ValidationResult,
    ) -> bool:
        """Validate value type.
        
        Args:
            value: Value to check
            expected_type: Expected type or tuple of types
            field_name: Field name for error reporting
            result: ValidationResult to accumulate errors
            
        Returns:
            True if valid, False otherwise
        """
        if not isinstance(value, expected_type):
            result.add_error(
                f"Field '{field_name}' has type {type(value).__name__}, "
                f"expected {expected_type.__name__ if hasattr(expected_type, '__name__') else str(expected_type)}",
                field=field_name,
                code="type_mismatch"
            )
            return False
        return True
    
    def _validate_range(
        self, 
        value: float, 
        min_val: Optional[float] = None, 
        max_val: Optional[float] = None, 
        field_name: str = "value",
        result: Optional[ValidationResult] = None,
    ) -> bool:
        """Validate numeric value is in range.
        
        Args:
            value: Numeric value to check
            min_val: Minimum allowed value (inclusive)
            max_val: Maximum allowed value (inclusive)
            field_name: Field name for error reporting
            result: ValidationResult to accumulate errors
            
        Returns:
            True if valid, False otherwise
        """
        if min_val is not None and value < min_val:
            msg = f"Field '{field_name}' value {value} is below minimum {min_val}"
            if result:
                result.add_error(msg, field=field_name, code="below_minimum")
            return False
        
        if max_val is not None and value > max_val:
            msg = f"Field '{field_name}' value {value} is above maximum {max_val}"
            if result:
                result.add_error(msg, field=field_name, code="above_maximum")
            return False
        
        return True


class EntityExtractionValidator(ResponseValidator):
    """Validator for entity extraction results."""
    
    def validate(self, data: Any) -> ValidationResult:
        """Validate entity extraction result.
        
        Expected structure:
        {
            'id': str,
            'name': str,
            'type': str,
            'confidence': float (0-1),
            'properties': dict (optional),
            'metadata': dict (optional),
        }
        """
        result = ValidationResult(is_valid=True)
        
        if not isinstance(data, dict):
            result.add_error("Entity must be a dictionary", code="type_error")
            return result
        
        # Required fields
        required_fields = ['id', 'name', 'type', 'confidence']
        for field in required_fields:
            if field not in data:
                result.add_error(f"Missing required field: {field}", field=field, code="missing_field")
        
        # Type checks
        if 'id' in data:
            self._validate_type(data['id'], str, 'id', result)
        
        if 'name' in data:
            self._validate_type(data['name'], (str, type(None)), 'name', result)
        
        if 'type' in data:
            self._validate_type(data['type'], str, 'type', result)
        
        if 'confidence' in data:
            self._validate_type(data['confidence'], (float, int), 'confidence', result)
            if isinstance(data['confidence'], (float, int)):
                self._validate_range(data['confidence'], 0.0, 1.0, 'confidence', result)
        
        if 'properties' in data and data['properties'] is not None:
            self._validate_type(data['properties'], dict, 'properties', result)
        
        if 'metadata' in data and data['metadata'] is not None:
            self._validate_type(data['metadata'], dict, 'metadata', result)
        
        # Check for extra fields if not allowed
        if not self.allow_extra_fields:
            allowed_fields = {'id', 'name', 'text', 'type', 'confidence', 'properties', 'metadata', 'source', 'source_span', 'context'}
            extra_fields = set(data.keys()) - allowed_fields
            if extra_fields:
                result.add_warning(f"Unknown fields: {', '.join(extra_fields)}")
        
        if result.errors:
            result.is_valid = False
        
        if result.is_valid:
            result.data = data
        
        return result


class RelationshipExtractionValidator(ResponseValidator):
    """Validator for relationship extraction results."""
    
    def validate(self, data: Any) -> ValidationResult:
        """Validate relationship extraction result.
        
        Expected structure:
        {
            'id': str,
            'source': str,
            'target': str,
            'type': str,
            'confidence': float (0-1),
            'type_confidence': float (0-1, optional),
            'properties': dict (optional),
            'metadata': dict (optional),
        }
        """
        result = ValidationResult(is_valid=True)
        
        if not isinstance(data, dict):
            result.add_error("Relationship must be a dictionary", code="type_error")
            return result
        
        # Required fields
        required_fields = ['source', 'target', 'type']
        for field in required_fields:
            if field not in data:
                result.add_error(f"Missing required field: {field}", field=field, code="missing_field")
        
        # Type checks
        for field in ['source', 'target', 'type']:
            if field in data:
                self._validate_type(data[field], str, field, result)
        
        if 'confidence' in data:
            self._validate_type(data['confidence'], (float, int), 'confidence', result)
            if isinstance(data['confidence'], (float, int)):
                self._validate_range(data['confidence'], 0.0, 1.0, 'confidence', result)
        
        if 'type_confidence' in data:
            self._validate_type(data['type_confidence'], (float, int), 'type_confidence', result)
            if isinstance(data['type_confidence'], (float, int)):
                self._validate_range(data['type_confidence'], 0.0, 1.0, 'type_confidence', result)
        
        # Ensure source != target
        if 'source' in data and 'target' in data and data['source'] == data['target']:
            result.add_warning("Self-relationships detected: source and target are identical", field="relationship")
        
        if result.errors:
            result.is_valid = False
        
        if result.is_valid:
            result.data = data
        
        return result


class CriticScoreValidator(ResponseValidator):
    """Validator for critic evaluation scores."""
    
    REQUIRED_DIMENSIONS = ['overall', 'completeness', 'consistency', 'clarity', 'granularity', 'domain_alignment']
    
    def validate(self, data: Any) -> ValidationResult:
        """Validate critic score dictionary.
        
        Expected structure:
        {
            'overall': float (0-100),
            'completeness': float,
            'consistency': float,
            'clarity': float,
            'granularity': float,
            'domain_alignment': float,
            'dimensions': dict (optional),
            'recommendations': list (optional),
        }
        """
        result = ValidationResult(is_valid=True)
        
        if not isinstance(data, dict):
            result.add_error("CriticScore must be a dictionary", code="type_error")
            return result
        
        # Validate required dimensions
        for dimension in self.REQUIRED_DIMENSIONS:
            if dimension not in data:
                if self.strict:
                    result.add_error(f"Missing required dimension: {dimension}", field=dimension, code="missing_field")
            else:
                value = data[dimension]
                self._validate_type(value, (float, int), dimension, result)
                
                # overall is 0-100, others are typically 0-1 but be flexible
                if dimension == 'overall':
                    self._validate_range(value, 0.0, 100.0, dimension, result)
                else:
                    if not (0.0 <= value <= 100.0):
                        # Allow both 0-1 and 0-100 scales
                        if not (0.0 <= value <= 1.0):
                            result.add_warning(
                                f"Dimension '{dimension}' value {value} outside expected range [0, 1] or [0, 100]",
                                field=dimension
                            )
        
        if 'recommendations' in data and data['recommendations'] is not None:
            if not isinstance(data['recommendations'], list):
                result.add_error("Field 'recommendations' must be a list", field='recommendations', code="type_error")
            else:
                for i, rec in enumerate(data['recommendations']):
                    if not isinstance(rec, str):
                        result.add_error(
                            f"Recommendation {i} is not a string",
                            field=f"recommendations[{i}]",
                            code="type_error"
                        )
        
        if result.errors:
            result.is_valid = False
        
        if result.is_valid:
            result.data = data
        
        return result


class OntologySessionValidator(ResponseValidator):
    """Validator for complete ontology session data."""
    
    def validate(self, data: Any) -> ValidationResult:
        """Validate ontology session structure."""
        result = ValidationResult(is_valid=True)
        
        if not isinstance(data, dict):
            result.add_error("OntologySession must be a dictionary", code="type_error")
            return result
        
        # Required fields
        required_fields = ['session_id', 'domain', 'status']
        for field in required_fields:
            if field not in data:
                result.add_error(f"Missing required field: {field}", field=field, code="missing_field")
        
        # Validate session_id is string
        if 'session_id' in data:
            self._validate_type(data['session_id'], str, 'session_id', result)
        
        # Validate status is one of allowed values
        valid_statuses = {'pending', 'running', 'completed', 'failed', 'cancelled'}
        if 'status' in data and data['status'] not in valid_statuses:
            result.add_error(
                f"Invalid status: {data['status']}. Must be one of {valid_statuses}",
                field='status',
                code="invalid_choice"
            )
        
        # Validate numeric fields if present
        numeric_fields = {
            'duration_ms': (0, float('inf')),
            'iterations': (0, float('inf')),
            'initial_score': (0, 100),
            'final_score': (0, 100),
            'improvement_score': (0, 100),
        }
        
        for field, (min_val, max_val) in numeric_fields.items():
            if field in data and data[field] is not None:
                self._validate_type(data[field], (float, int), field, result)
                if isinstance(data[field], (float, int)):
                    self._validate_range(data[field], min_val, max_val, field, result)
        
        if result.errors:
            result.is_valid = False
        
        if result.is_valid:
            result.data = data
        
        return result


class QueryPlanValidator(ResponseValidator):
    """Validator for query execution plans."""
    
    def validate(self, data: Any) -> ValidationResult:
        """Validate query plan structure."""
        result = ValidationResult(is_valid=True)
        
        if not isinstance(data, dict):
            result.add_error("QueryPlan must be a dictionary", code="type_error")
            return result
        
        # Required fields
        required_fields = ['query_id', 'query_text', 'plan_type', 'steps']
        for field in required_fields:
            if field not in data:
                result.add_error(f"Missing required field: {field}", field=field, code="missing_field")
        
        # Validate plan_type
        valid_plan_types = {'vector', 'direct', 'traversal', 'hybrid', 'keyword', 'semantic'}
        if 'plan_type' in data and data['plan_type'] not in valid_plan_types:
            result.add_error(
                f"Invalid plan_type: {data['plan_type']}. Must be one of {valid_plan_types}",
                field='plan_type',
                code="invalid_choice"
            )
        
        # Validate steps is list
        if 'steps' in data:
            if not isinstance(data['steps'], list):
                result.add_error("Field 'steps' must be a list", field='steps', code="type_error")
            else:
                if len(data['steps']) == 0 and self.strict:
                    result.add_warning("Query plan has no steps", field='steps')
        
        # Validate optional numeric fields
        if 'estimated_cost' in data and data['estimated_cost'] is not None:
            self._validate_type(data['estimated_cost'], (float, int), 'estimated_cost', result)
            if isinstance(data['estimated_cost'], (float, int)):
                self._validate_range(data['estimated_cost'], 0.0, float('inf'), 'estimated_cost', result)
        
        if 'timeout_ms' in data and data['timeout_ms'] is not None:
            self._validate_type(data['timeout_ms'], (int, float), 'timeout_ms', result)
            if isinstance(data['timeout_ms'], (int, float)):
                self._validate_range(data['timeout_ms'], 0.0, float('inf'), 'timeout_ms', result)
        
        if result.errors:
            result.is_valid = False
        
        if result.is_valid:
            result.data = data
        
        return result


def validate_batch(
    data_items: List[Any],
    validator: ResponseValidator,
) -> Tuple[List[Any], List[ValidationResult]]:
    """Validate a batch of items.
    
    Args:
        data_items: List of items to validate
        validator: Validator instance to use
        
    Returns:
        Tuple of (valid_items, validation_results)
    """
    valid_items = []
    results = []
    
    for item in data_items:
        result = validator.validate(item)
        results.append(result)
        if result.is_valid:
            valid_items.append(result.data or item)
    
    return valid_items, results


if __name__ == '__main__':
    # Example usage
    entity_data = {
        'id': 'e1',
        'name': 'John Smith',
        'type': 'Person',
        'confidence': 0.95,
        'properties': {'role': 'CEO'},
    }
    
    entity_validator = EntityExtractionValidator()
    entity_result = entity_validator.validate(entity_data)
    print(f"Entity valid: {entity_result.is_valid}")
    
    # Validate batch
    entities = [
        {'id': 'e1', 'name': 'John', 'type': 'Person', 'confidence': 0.9},
        {'id': 'e2', 'name': 'ACME', 'type': 'Organization', 'confidence': 0.85},
    ]
    
    valid_entities, results = validate_batch(entities, entity_validator)
    print(f"Batch validation: {len(valid_entities)} valid out of {len(entities)}")
