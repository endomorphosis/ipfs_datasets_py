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
        
        # Validate target class
        if "targetClass" in shape:
            target_class = shape["targetClass"]
            data_type = data.get("@type", "")
            if isinstance(data_type, str):
                if data_type != target_class and not data_type.endswith(target_class):
                    result.add_error(f"Type mismatch: expected {target_class}, got {data_type}")
        
        # Validate property constraints
        if "property" in shape:
            properties = shape["property"]
            if not isinstance(properties, list):
                properties = [properties]
            
            for prop_constraint in properties:
                self._validate_property_constraint(data, prop_constraint, result)
        
        return result
    
    def _validate_property_constraint(
        self,
        data: Dict[str, Any],
        constraint: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """
        Validate a property constraint.
        
        Args:
            data: Data to validate
            constraint: Property constraint
            result: ValidationResult to update
        """
        path = constraint.get("path", "")
        
        # Check minCount
        if "minCount" in constraint:
            min_count = constraint["minCount"]
            value = data.get(path)
            
            if value is None:
                if min_count > 0:
                    result.add_error(f"Property {path} is required (minCount={min_count})")
            elif isinstance(value, list):
                if len(value) < min_count:
                    result.add_error(
                        f"Property {path} has {len(value)} values, "
                        f"but requires at least {min_count}"
                    )
        
        # Check maxCount
        if "maxCount" in constraint:
            max_count = constraint["maxCount"]
            value = data.get(path)
            
            if value is not None and isinstance(value, list):
                if len(value) > max_count:
                    result.add_error(
                        f"Property {path} has {len(value)} values, "
                        f"but allows at most {max_count}"
                    )
        
        # Check datatype
        if "datatype" in constraint:
            expected_type = constraint["datatype"]
            value = data.get(path)
            
            if value is not None:
                if not self._check_datatype(value, expected_type):
                    result.add_error(
                        f"Property {path} has wrong datatype: "
                        f"expected {expected_type}"
                    )
    
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
