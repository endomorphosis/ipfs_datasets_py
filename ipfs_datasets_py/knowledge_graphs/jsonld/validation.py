"""
Schema Validation for JSON-LD

This module provides validation against JSON Schema and basic SHACL shapes.
"""

import logging
from typing import Any, Dict, List, Optional

from .types import ValidationResult

logger = logging.getLogger(__name__)

# Check for jsonschema library
try:
    import jsonschema
    from jsonschema import Draft7Validator, validators
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False
    logger.warning("jsonschema library not available - validation will be limited")


class SchemaValidator:
    """
    Validates JSON-LD documents against JSON Schema.
    
    Supports JSON Schema Draft 7.
    """
    
    def __init__(self):
        """Initialize the schema validator."""
        self.schemas: Dict[str, Dict[str, Any]] = {}
    
    def register_schema(self, schema_id: str, schema: Dict[str, Any]) -> None:
        """
        Register a JSON Schema.
        
        Args:
            schema_id: Unique identifier for the schema
            schema: JSON Schema definition
        """
        self.schemas[schema_id] = schema
    
    def validate(self, data: Dict[str, Any], schema: Optional[Dict[str, Any]] = None) -> ValidationResult:
        """
        Validate data against a JSON Schema.
        
        Args:
            data: Data to validate
            schema: Schema to validate against (if None, try to detect from data)
            
        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult(valid=True)
        
        if not HAVE_JSONSCHEMA:
            result.add_warning("jsonschema library not available - skipping validation")
            return result
        
        # Auto-detect schema if not provided
        if schema is None:
            schema = self._detect_schema(data)
        
        if schema is None:
            result.add_warning("No schema provided and could not auto-detect")
            return result
        
        # Validate using jsonschema
        try:
            validator = Draft7Validator(schema)
            errors = list(validator.iter_errors(data))
            
            if errors:
                for error in errors:
                    error_path = ".".join(str(p) for p in error.path)
                    error_msg = f"{error_path}: {error.message}" if error_path else error.message
                    result.add_error(error_msg)
        except Exception as e:
            result.add_error(f"Validation error: {str(e)}")
        
        return result
    
    def _detect_schema(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Try to detect which schema to use based on data.
        
        Args:
            data: Data to inspect
            
        Returns:
            Schema or None if not detected
        """
        # Check for @type to determine schema
        if "@type" in data:
            schema_type = data["@type"]
            if isinstance(schema_type, str):
                return self.schemas.get(schema_type)
        
        return None


class SHACLValidator:
    """
    Basic SHACL (Shapes Constraint Language) validator.
    
    Supports a subset of SHACL shapes for property constraints.
    """
    
    def __init__(self):
        """Initialize the SHACL validator."""
        self.shapes: Dict[str, Dict[str, Any]] = {}
    
    def register_shape(self, shape_id: str, shape: Dict[str, Any]) -> None:
        """
        Register a SHACL shape.
        
        Args:
            shape_id: Unique identifier for the shape
            shape: SHACL shape definition
        """
        self.shapes[shape_id] = shape
    
    def validate(self, data: Dict[str, Any], shape: Optional[Dict[str, Any]] = None) -> ValidationResult:
        """
        Validate data against a SHACL shape.
        
        Args:
            data: Data to validate
            shape: Shape to validate against
            
        Returns:
            ValidationResult with errors and warnings
        """
        result = ValidationResult(valid=True)
        
        if shape is None:
            # Try to detect shape from data
            shape = self._detect_shape(data)
        
        if shape is None:
            result.add_warning("No shape provided and could not auto-detect")
            return result
        
        # Get severity level (default to Violation)
        severity = shape.get("severity", "Violation")
        
        # Handle shape composition: sh:and
        if "and" in shape:
            and_shapes = shape["and"]
            if not isinstance(and_shapes, list):
                and_shapes = [and_shapes]
            
            for and_shape in and_shapes:
                and_result = self.validate(data, and_shape)
                if not and_result.valid:
                    result.valid = False
                    for error in and_result.errors:
                        self._add_error_with_severity(result, error, severity)
        
        # Handle shape composition: sh:or
        if "or" in shape:
            or_shapes = shape["or"]
            if not isinstance(or_shapes, list):
                or_shapes = [or_shapes]
            
            or_valid = False
            or_errors = []
            for or_shape in or_shapes:
                or_result = self.validate(data, or_shape)
                if or_result.valid:
                    or_valid = True
                    break
                else:
                    or_errors.extend(or_result.errors)
            
            if not or_valid:
                error_msg = f"None of the OR conditions satisfied: {'; '.join(or_errors)}"
                self._add_error_with_severity(result, error_msg, severity)
        
        # Handle shape composition: sh:not
        if "not" in shape:
            not_shape = shape["not"]
            not_result = self.validate(data, not_shape)
            if not_result.valid:
                error_msg = "Data matches a NOT condition (should not match)"
                self._add_error_with_severity(result, error_msg, severity)
        
        # Validate target class
        if "targetClass" in shape:
            target_class = shape["targetClass"]
            data_type = data.get("@type", "")
            if isinstance(data_type, str):
                if data_type != target_class and not data_type.endswith(target_class):
                    error_msg = f"Type mismatch: expected {target_class}, got {data_type}"
                    self._add_error_with_severity(result, error_msg, severity)
        
        # Validate property constraints
        if "property" in shape:
            properties = shape["property"]
            if not isinstance(properties, list):
                properties = [properties]
            
            for prop_constraint in properties:
                self._validate_property_constraint(data, prop_constraint, result, severity)
        
        return result
    
    def _add_error_with_severity(self, result: ValidationResult, message: str, severity: str) -> None:
        """
        Add an error or warning based on severity level.
        
        Args:
            result: ValidationResult to update
            message: Error/warning message
            severity: Severity level (Violation, Warning, Info)
        """
        if severity == "Warning" or severity == "Info":
            result.add_warning(f"[{severity}] {message}")
        else:
            result.add_error(f"[{severity}] {message}")
    
    def _validate_property_constraint(
        self,
        data: Dict[str, Any],
        constraint: Dict[str, Any],
        result: ValidationResult,
        severity: str = "Violation"
    ) -> None:
        """
        Validate a property constraint.
        
        Args:
            data: Data to validate
            constraint: Property constraint
            result: ValidationResult to update
            severity: Severity level for violations
        """
        path = constraint.get("path", "")
        
        # Override severity if specified in constraint
        constraint_severity = constraint.get("severity", severity)
        
        # Check minCount
        if "minCount" in constraint:
            min_count = constraint["minCount"]
            value = data.get(path)
            
            if value is None:
                if min_count > 0:
                    error_msg = f"Property {path} is required (minCount={min_count})"
                    self._add_error_with_severity(result, error_msg, constraint_severity)
            else:
                value_count = len(value) if isinstance(value, list) else 1
                if value_count < min_count:
                    error_msg = (
                        f"Property {path} has {value_count} values, "
                        f"but requires at least {min_count}"
                    )
                    self._add_error_with_severity(result, error_msg, constraint_severity)
        
        # Check maxCount
        if "maxCount" in constraint:
            max_count = constraint["maxCount"]
            value = data.get(path)

            if value is not None:
                value_count = len(value) if isinstance(value, list) else 1
                if value_count > max_count:
                    error_msg = (
                        f"Property {path} has {value_count} values, "
                        f"but allows at most {max_count}"
                    )
                    self._add_error_with_severity(result, error_msg, constraint_severity)

        # Check hasValue
        if "hasValue" in constraint:
            expected_value = constraint["hasValue"]
            value = data.get(path)

            if value is None:
                error_msg = f"Property {path} must have value {expected_value}"
                self._add_error_with_severity(result, error_msg, constraint_severity)
            elif isinstance(value, list):
                if expected_value not in value:
                    error_msg = f"Property {path} must contain value {expected_value}"
                    self._add_error_with_severity(result, error_msg, constraint_severity)
            else:
                if value != expected_value:
                    error_msg = f"Property {path} must have value {expected_value}"
                    self._add_error_with_severity(result, error_msg, constraint_severity)
        
        # Check datatype
        if "datatype" in constraint:
            expected_type = constraint["datatype"]
            value = data.get(path)
            
            if value is not None:
                if not self._check_datatype(value, expected_type):
                    error_msg = (
                        f"Property {path} has wrong datatype: "
                        f"expected {expected_type}"
                    )
                    self._add_error_with_severity(result, error_msg, constraint_severity)
        
        # Check sh:class constraint
        if "class" in constraint:
            expected_class = constraint["class"]
            value = data.get(path)
            
            if value is not None:
                if isinstance(value, dict):
                    value_type = value.get("@type", "")
                    if value_type != expected_class and not value_type.endswith(expected_class):
                        error_msg = (
                            f"Property {path} value has wrong class: "
                            f"expected {expected_class}, got {value_type}"
                        )
                        self._add_error_with_severity(result, error_msg, constraint_severity)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            item_type = item.get("@type", "")
                            if item_type != expected_class and not item_type.endswith(expected_class):
                                error_msg = (
                                    f"Property {path} list item has wrong class: "
                                    f"expected {expected_class}, got {item_type}"
                                )
                                self._add_error_with_severity(result, error_msg, constraint_severity)
        
        # Check sh:pattern constraint (regex)
        if "pattern" in constraint:
            import re
            pattern = constraint["pattern"]
            value = data.get(path)
            
            if value is not None:
                values_to_check = [value] if not isinstance(value, list) else value
                for val in values_to_check:
                    if isinstance(val, str):
                        if not re.match(pattern, val):
                            error_msg = f"Property {path} value '{val}' does not match pattern {pattern}"
                            self._add_error_with_severity(result, error_msg, constraint_severity)
        
        # Check sh:in constraint (enumeration)
        if "in" in constraint:
            allowed_values = constraint["in"]
            value = data.get(path)
            
            if value is not None:
                values_to_check = [value] if not isinstance(value, list) else value
                for val in values_to_check:
                    if val not in allowed_values:
                        error_msg = f"Property {path} value '{val}' not in allowed values: {allowed_values}"
                        self._add_error_with_severity(result, error_msg, constraint_severity)
        
        # Check sh:node constraint (nested shape)
        if "node" in constraint:
            nested_shape = constraint["node"]
            value = data.get(path)
            
            if value is not None:
                values_to_check = [value] if not isinstance(value, list) else value
                for val in values_to_check:
                    if isinstance(val, dict):
                        nested_result = self.validate(val, nested_shape)
                        if not nested_result.valid:
                            for error in nested_result.errors:
                                error_msg = f"Property {path} nested validation: {error}"
                                self._add_error_with_severity(result, error_msg, constraint_severity)
        
        # Check sh:minLength and sh:maxLength
        if "minLength" in constraint or "maxLength" in constraint:
            value = data.get(path)
            if value is not None:
                values_to_check = [value] if not isinstance(value, list) else value
                for val in values_to_check:
                    if isinstance(val, str):
                        if "minLength" in constraint:
                            min_length = constraint["minLength"]
                            if len(val) < min_length:
                                error_msg = (
                                    f"Property {path} value length {len(val)} is less than minLength {min_length}"
                                )
                                self._add_error_with_severity(result, error_msg, constraint_severity)
                        if "maxLength" in constraint:
                            max_length = constraint["maxLength"]
                            if len(val) > max_length:
                                error_msg = (
                                    f"Property {path} value length {len(val)} exceeds maxLength {max_length}"
                                )
                                self._add_error_with_severity(result, error_msg, constraint_severity)
        
        # Check sh:minInclusive and sh:maxInclusive
        if "minInclusive" in constraint or "maxInclusive" in constraint:
            value = data.get(path)
            if value is not None:
                values_to_check = [value] if not isinstance(value, list) else value
                for val in values_to_check:
                    if isinstance(val, (int, float)):
                        if "minInclusive" in constraint:
                            min_val = constraint["minInclusive"]
                            if val < min_val:
                                error_msg = f"Property {path} value {val} is less than minInclusive {min_val}"
                                self._add_error_with_severity(result, error_msg, constraint_severity)
                        if "maxInclusive" in constraint:
                            max_val = constraint["maxInclusive"]
                            if val > max_val:
                                error_msg = f"Property {path} value {val} exceeds maxInclusive {max_val}"
                                self._add_error_with_severity(result, error_msg, constraint_severity)
    
    def _check_datatype(self, value: Any, expected_type: str) -> bool:
        """
        Check if value matches expected datatype.
        
        Args:
            value: Value to check
            expected_type: Expected XSD datatype
            
        Returns:
            True if type matches
        """
        # Map XSD types to Python types
        type_map = {
            "xsd:string": str,
            "xsd:integer": int,
            "xsd:decimal": (int, float),
            "xsd:boolean": bool,
            "xsd:float": float,
            "xsd:double": float,
        }
        
        python_type = type_map.get(expected_type, str)
        return isinstance(value, python_type)
    
    def _detect_shape(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Try to detect which shape to use based on data.
        
        Args:
            data: Data to inspect
            
        Returns:
            Shape or None if not detected
        """
        # Check for @type to determine shape
        if "@type" in data:
            data_type = data["@type"]
            if isinstance(data_type, str):
                # Find shape targeting this class
                for shape in self.shapes.values():
                    if shape.get("targetClass") == data_type:
                        return shape
        
        return None


class SemanticValidator:
    """
    Composite validator combining JSON Schema and SHACL validation.
    """
    
    def __init__(self):
        """Initialize the semantic validator."""
        self.schema_validator = SchemaValidator()
        self.shacl_validator = SHACLValidator()
    
    def register_schema(self, schema_id: str, schema: Dict[str, Any]) -> None:
        """Register a JSON Schema."""
        self.schema_validator.register_schema(schema_id, schema)
    
    def register_shape(self, shape_id: str, shape: Dict[str, Any]) -> None:
        """Register a SHACL shape."""
        self.shacl_validator.register_shape(shape_id, shape)
    
    def validate(
        self,
        data: Dict[str, Any],
        schema: Optional[Dict[str, Any]] = None,
        shape: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validate data using both JSON Schema and SHACL.
        
        Args:
            data: Data to validate
            schema: Optional JSON Schema
            shape: Optional SHACL shape
            
        Returns:
            Combined validation result
        """
        result = ValidationResult(valid=True)
        
        # Validate with JSON Schema
        schema_result = self.schema_validator.validate(data, schema)
        result.errors.extend(schema_result.errors)
        result.warnings.extend(schema_result.warnings)
        if not schema_result.valid:
            result.valid = False
        
        # Validate with SHACL
        shacl_result = self.shacl_validator.validate(data, shape)
        result.errors.extend(shacl_result.errors)
        result.warnings.extend(shacl_result.warnings)
        if not shacl_result.valid:
            result.valid = False
        
        return result
