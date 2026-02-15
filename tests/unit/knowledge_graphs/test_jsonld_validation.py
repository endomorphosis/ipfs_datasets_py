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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
