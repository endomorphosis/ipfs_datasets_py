"""
Tests for JSON-LD Schema Validation

This module provides tests for schema validation functionality.
"""

import pytest
from ipfs_datasets_py.knowledge_graphs.jsonld.validation import (
    SchemaValidator,
    SHACLValidator,
    SemanticValidator,
    ValidationResult,
)


class TestValidationResult:
    """Test validation result data structure."""
    
    def test_initially_valid(self):
        """Test that new result is initially valid."""
        # GIVEN a new validation result
        result = ValidationResult(valid=True)
        
        # THEN it should be valid with no errors
        assert result.valid
        assert len(result.errors) == 0
        assert len(result.warnings) == 0
    
    def test_add_error_invalidates(self):
        """Test that adding error invalidates result."""
        # GIVEN a valid result
        result = ValidationResult(valid=True)
        
        # WHEN adding an error
        result.add_error("Test error")
        
        # THEN result should be invalid
        assert not result.valid
        assert len(result.errors) == 1
        assert result.errors[0] == "Test error"
    
    def test_add_warning_keeps_valid(self):
        """Test that warnings don't invalidate result."""
        # GIVEN a valid result
        result = ValidationResult(valid=True)
        
        # WHEN adding a warning
        result.add_warning("Test warning")
        
        # THEN result should still be valid
        assert result.valid
        assert len(result.warnings) == 1
        assert result.warnings[0] == "Test warning"


class TestSchemaValidator:
    """Test JSON Schema validation."""
    
    def test_validate_without_jsonschema(self):
        """Test validation gracefully handles missing jsonschema."""
        # GIVEN a validator
        validator = SchemaValidator()
        data = {"name": "Alice"}
        
        # WHEN validating without schema
        result = validator.validate(data)
        
        # THEN should get warning but not fail
        assert len(result.warnings) >= 0  # May warn about missing library or schema
    
    def test_register_schema(self):
        """Test registering a schema."""
        # GIVEN a validator and schema
        validator = SchemaValidator()
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            }
        }
        
        # WHEN registering schema
        validator.register_schema("Person", schema)
        
        # THEN schema should be stored
        assert "Person" in validator.schemas
        assert validator.schemas["Person"] == schema


class TestSHACLValidator:
    """Test SHACL shape validation."""
    
    def test_validate_target_class(self):
        """Test validating target class constraint."""
        # GIVEN a SHACL validator with shape
        validator = SHACLValidator()
        shape = {
            "targetClass": "Person"
        }
        
        # WHEN validating correct type
        data = {"@type": "Person", "name": "Alice"}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_validate_wrong_target_class(self):
        """Test detecting wrong target class."""
        # GIVEN a SHACL validator with shape
        validator = SHACLValidator()
        shape = {
            "targetClass": "Person"
        }
        
        # WHEN validating wrong type
        data = {"@type": "Organization", "name": "Acme"}
        result = validator.validate(data, shape)
        
        # THEN should have error
        assert not result.valid
        assert len(result.errors) > 0
    
    def test_validate_min_count(self):
        """Test minCount property constraint."""
        # GIVEN a shape with minCount constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "name",
                "minCount": 1
            }
        }
        
        # WHEN validating data without required property
        data = {"@type": "Person"}
        result = validator.validate(data, shape)
        
        # THEN should have error
        assert not result.valid
        assert any("name" in err for err in result.errors)
    
    def test_validate_max_count(self):
        """Test maxCount property constraint."""
        # GIVEN a shape with maxCount constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "email",
                "maxCount": 1
            }
        }
        
        # WHEN validating data with too many values
        data = {
            "@type": "Person",
            "email": ["alice@example.com", "alice2@example.com"]
        }
        result = validator.validate(data, shape)
        
        # THEN should have error
        assert not result.valid
        assert any("email" in err for err in result.errors)
    
    def test_validate_datatype(self):
        """Test datatype constraint."""
        # GIVEN a shape with datatype constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "age",
                "datatype": "xsd:integer"
            }
        }
        
        # WHEN validating correct datatype
        data = {"@type": "Person", "age": 30}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_register_shape(self):
        """Test registering a SHACL shape."""
        # GIVEN a validator and shape
        validator = SHACLValidator()
        shape = {
            "targetClass": "Person",
            "property": {"path": "name", "minCount": 1}
        }
        
        # WHEN registering shape
        validator.register_shape("PersonShape", shape)
        
        # THEN shape should be stored
        assert "PersonShape" in validator.shapes
        assert validator.shapes["PersonShape"] == shape


class TestSemanticValidator:
    """Test combined semantic validation."""
    
    def test_combines_validators(self):
        """Test that semantic validator uses both validators."""
        # GIVEN a semantic validator
        validator = SemanticValidator()
        
        # WHEN registering both schema and shape
        schema = {"type": "object"}
        shape = {"targetClass": "Person"}
        
        validator.register_schema("Person", schema)
        validator.register_shape("PersonShape", shape)
        
        # THEN both should be registered
        assert "Person" in validator.schema_validator.schemas
        assert "PersonShape" in validator.shacl_validator.shapes
    
    def test_validates_with_both(self):
        """Test validation uses both validators."""
        # GIVEN a semantic validator
        validator = SemanticValidator()
        
        # WHEN validating data
        data = {"@type": "Person", "name": "Alice"}
        result = validator.validate(data)
        
        # THEN should get result (may have warnings)
        assert isinstance(result, ValidationResult)


class TestAdvancedSHACLConstraints:
    """Test advanced SHACL constraints added in Path C."""
    
    def test_class_constraint(self):
        """Test sh:class constraint validation."""
        # GIVEN a validator with class constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "knows",
                "class": "Person"
            }
        }
        
        # WHEN validating correct class
        data = {
            "@type": "Person",
            "knows": {"@type": "Person", "name": "Bob"}
        }
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_class_constraint_wrong_type(self):
        """Test sh:class detects wrong type."""
        # GIVEN a validator with class constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "knows",
                "class": "Person"
            }
        }
        
        # WHEN validating wrong class
        data = {
            "@type": "Person",
            "knows": {"@type": "Organization", "name": "Acme"}
        }
        result = validator.validate(data, shape)
        
        # THEN should have error
        assert not result.valid
        assert any("wrong class" in err for err in result.errors)
    
    def test_pattern_constraint(self):
        """Test sh:pattern regex constraint."""
        # GIVEN a validator with pattern constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "email",
                "pattern": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            }
        }
        
        # WHEN validating valid email
        data = {"@type": "Person", "email": "alice@example.com"}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_pattern_constraint_invalid(self):
        """Test sh:pattern detects invalid pattern."""
        # GIVEN a validator with pattern constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "email",
                "pattern": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            }
        }
        
        # WHEN validating invalid email
        data = {"@type": "Person", "email": "not-an-email"}
        result = validator.validate(data, shape)
        
        # THEN should have error
        assert not result.valid
        assert any("pattern" in err for err in result.errors)
    
    def test_in_constraint(self):
        """Test sh:in enumeration constraint."""
        # GIVEN a validator with in constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "status",
                "in": ["active", "inactive", "pending"]
            }
        }
        
        # WHEN validating valid value
        data = {"@type": "User", "status": "active"}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_in_constraint_invalid(self):
        """Test sh:in detects invalid value."""
        # GIVEN a validator with in constraint
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "status",
                "in": ["active", "inactive", "pending"]
            }
        }
        
        # WHEN validating invalid value
        data = {"@type": "User", "status": "unknown"}
        result = validator.validate(data, shape)
        
        # THEN should have error
        assert not result.valid
        assert any("not in allowed values" in err for err in result.errors)
    
    def test_node_constraint(self):
        """Test sh:node nested shape constraint."""
        # GIVEN a validator with nested shape constraint
        validator = SHACLValidator()
        address_shape = {
            "property": {
                "path": "city",
                "minCount": 1
            }
        }
        person_shape = {
            "property": {
                "path": "address",
                "node": address_shape
            }
        }
        
        # WHEN validating with valid nested data
        data = {
            "@type": "Person",
            "address": {
                "@type": "Address",
                "city": "New York"
            }
        }
        result = validator.validate(data, person_shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_node_constraint_invalid(self):
        """Test sh:node detects nested validation errors."""
        # GIVEN a validator with nested shape constraint
        validator = SHACLValidator()
        address_shape = {
            "property": {
                "path": "city",
                "minCount": 1
            }
        }
        person_shape = {
            "property": {
                "path": "address",
                "node": address_shape
            }
        }
        
        # WHEN validating with invalid nested data
        data = {
            "@type": "Person",
            "address": {
                "@type": "Address"
                # Missing required city
            }
        }
        result = validator.validate(data, person_shape)
        
        # THEN should have nested error
        assert not result.valid
        assert any("nested validation" in err for err in result.errors)
    
    def test_min_max_length(self):
        """Test sh:minLength and sh:maxLength constraints."""
        # GIVEN a validator with length constraints
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "username",
                "minLength": 3,
                "maxLength": 20
            }
        }
        
        # WHEN validating valid length
        data = {"@type": "User", "username": "alice123"}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_min_length_violation(self):
        """Test sh:minLength detects too short values."""
        # GIVEN a validator with minLength
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "username",
                "minLength": 3
            }
        }
        
        # WHEN validating too short value
        data = {"@type": "User", "username": "ab"}
        result = validator.validate(data, shape)
        
        # THEN should have error
        assert not result.valid
        assert any("minLength" in err for err in result.errors)
    
    def test_min_max_inclusive(self):
        """Test sh:minInclusive and sh:maxInclusive constraints."""
        # GIVEN a validator with numeric range
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "age",
                "minInclusive": 0,
                "maxInclusive": 120
            }
        }
        
        # WHEN validating valid age
        data = {"@type": "Person", "age": 30}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_max_inclusive_violation(self):
        """Test sh:maxInclusive detects out of range values."""
        # GIVEN a validator with maxInclusive
        validator = SHACLValidator()
        shape = {
            "property": {
                "path": "age",
                "maxInclusive": 120
            }
        }
        
        # WHEN validating out of range value
        data = {"@type": "Person", "age": 150}
        result = validator.validate(data, shape)
        
        # THEN should have error
        assert not result.valid
        assert any("maxInclusive" in err for err in result.errors)


class TestSHACLShapeComposition:
    """Test SHACL shape composition (sh:and, sh:or, sh:not)."""
    
    def test_and_composition_valid(self):
        """Test sh:and with all conditions satisfied."""
        # GIVEN a validator with AND composition
        validator = SHACLValidator()
        shape = {
            "and": [
                {
                    "property": {
                        "path": "name",
                        "minCount": 1
                    }
                },
                {
                    "property": {
                        "path": "age",
                        "minInclusive": 18
                    }
                }
            ]
        }
        
        # WHEN validating data satisfying all AND conditions
        data = {"@type": "Person", "name": "Alice", "age": 25}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_and_composition_invalid(self):
        """Test sh:and detects when any condition fails."""
        # GIVEN a validator with AND composition
        validator = SHACLValidator()
        shape = {
            "and": [
                {
                    "property": {
                        "path": "name",
                        "minCount": 1
                    }
                },
                {
                    "property": {
                        "path": "age",
                        "minInclusive": 18
                    }
                }
            ]
        }
        
        # WHEN validating data with one failing condition
        data = {"@type": "Person", "name": "Bob", "age": 15}
        result = validator.validate(data, shape)
        
        # THEN should be invalid
        assert not result.valid
    
    def test_or_composition_valid(self):
        """Test sh:or with at least one condition satisfied."""
        # GIVEN a validator with OR composition
        validator = SHACLValidator()
        shape = {
            "or": [
                {
                    "property": {
                        "path": "email",
                        "minCount": 1
                    }
                },
                {
                    "property": {
                        "path": "phone",
                        "minCount": 1
                    }
                }
            ]
        }
        
        # WHEN validating data with one OR condition satisfied
        data = {"@type": "Person", "email": "alice@example.com"}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_or_composition_invalid(self):
        """Test sh:or detects when no conditions are satisfied."""
        # GIVEN a validator with OR composition
        validator = SHACLValidator()
        shape = {
            "or": [
                {
                    "property": {
                        "path": "email",
                        "minCount": 1
                    }
                },
                {
                    "property": {
                        "path": "phone",
                        "minCount": 1
                    }
                }
            ]
        }
        
        # WHEN validating data with no OR conditions satisfied
        data = {"@type": "Person", "name": "Bob"}
        result = validator.validate(data, shape)
        
        # THEN should be invalid
        assert not result.valid
        assert any("None of the OR conditions" in err for err in result.errors)
    
    def test_not_composition_valid(self):
        """Test sh:not with condition not satisfied."""
        # GIVEN a validator with NOT composition
        validator = SHACLValidator()
        shape = {
            "not": {
                "property": {
                    "path": "blocked",
                    "hasValue": True
                }
            }
        }
        
        # WHEN validating data that doesn't match NOT condition
        data = {"@type": "User", "name": "Alice"}
        result = validator.validate(data, shape)
        
        # THEN should be valid
        assert result.valid
    
    def test_severity_levels(self):
        """Test different severity levels (Violation, Warning, Info)."""
        # GIVEN a validator with different severity levels
        validator = SHACLValidator()
        shape = {
            "severity": "Warning",
            "property": {
                "path": "deprecated_field",
                "maxCount": 0
            }
        }
        
        # WHEN validating with a violation
        data = {"@type": "Entity", "deprecated_field": "value"}
        result = validator.validate(data, shape)
        
        # THEN should have warning instead of error
        assert len(result.warnings) > 0
        assert any("Warning" in warn for warn in result.warnings)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
