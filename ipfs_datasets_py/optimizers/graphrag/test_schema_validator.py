"""Tests for ontology schema validation.

Validates:
- Required fields (id, type, description for entities; source, target, type for relationships)
- Type constraints (IDs are strings, confidence is float)
- Confidence range validation (0.0 to 1.0)
- Entity reference integrity (relationships reference existing entities)
- No duplicate IDs
"""

import pytest
from typing import Any, Dict

from .schema_validator import (
    validate_ontology_schema,
    OntologySchemaError,
)


class TestTopLevelStructure:
    """Test top-level ontology structure validation."""
    
    def test_valid_minimal_ontology(self):
        """Minimal valid ontology passes validation."""
        ontology = {
            "entities": [],
            "relationships": [],
        }
        # Should not raise
        validate_ontology_schema(ontology)
    
    def test_non_dict_input_raises(self):
        """Non-dict input raises OntologySchemaError."""
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema("not a dict")  # type: ignore
        
        assert "must be a dictionary" in str(exc_info.value)
    
    def test_missing_entities_key_raises(self):
        """Missing 'entities' key raises."""
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema({"relationships": []})
        
        assert "entities" in str(exc_info.value)
        assert "Missing required key" in exc_info.value.errors[0]
    
    def test_missing_relationships_key_raises(self):
        """Missing 'relationships' key raises."""
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema({"entities": []})
        
        assert "relationships" in str(exc_info.value)
        assert "Missing required key" in exc_info.value.errors[0]
    
    def test_entities_not_list_raises(self):
        """entities value not being a list raises."""
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema({"entities": "not a list", "relationships": []})
        
        assert "'entities' must be a list" in exc_info.value.errors[0]
    
    def test_relationships_not_list_raises(self):
        """relationships value not being a list raises."""
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema({"entities": [], "relationships": "not a list"})
        
        assert "'relationships' must be a list" in exc_info.value.errors[0]


class TestEntityValidation:
    """Test entity structure validation."""
    
    def test_valid_entity(self):
        """Valid entity passes validation."""
        ontology = {
            "entities": [
                {
                    "id": "e1",
                    "type": "Person",
                    "description": "A person entity",
                    "confidence": 0.95,
                }
            ],
            "relationships": [],
        }
        # Should not raise
        validate_ontology_schema(ontology)
    
    def test_entity_without_confidence_passes_non_strict(self):
        """Entity without confidence passes in non-strict mode."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "description": "A person"}
            ],
            "relationships": [],
        }
        # Should not raise
        validate_ontology_schema(ontology, strict=False)
    
    def test_entity_without_confidence_fails_strict(self):
        """Entity without confidence fails in strict mode."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "description": "A person"}
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology, strict=True)
        
        assert "missing required field 'confidence'" in exc_info.value.errors[0]
    
    def test_entity_non_dict_raises(self):
        """Entity that is not a dict raises."""
        ontology = {
            "entities": ["not a dict"],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "must be a dict" in exc_info.value.errors[0]
    
    def test_entity_missing_id_raises(self):
        """Entity missing 'id' field raises."""
        ontology = {
            "entities": [
                {"type": "Person", "description": "Missing ID"}
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "missing required field 'id'" in exc_info.value.errors[0]
    
    def test_entity_missing_type_raises(self):
        """Entity missing 'type' field raises."""
        ontology = {
            "entities": [
                {"id": "e1", "description": "Missing type"}
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "missing required field 'type'" in exc_info.value.errors[0]
    
    def test_entity_missing_description_raises(self):
        """Entity missing 'description' field raises."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"}
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "missing required field 'description'" in exc_info.value.errors[0]
    
    def test_entity_non_string_id_raises(self):
        """Entity with non-string ID raises."""
        ontology = {
            "entities": [
                {"id": 123, "type": "Person", "description": "Bad ID type"}
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "'id' must be a string" in exc_info.value.errors[0]
    
    def test_duplicate_entity_ids_raises(self):
        """Duplicate entity IDs raise."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "description": "First"},
                {"id": "e1", "type": "Person", "description": "Duplicate ID"},
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "duplicate entity ID 'e1'" in exc_info.value.errors[0]
    
    def test_entity_confidence_out_of_range_raises(self):
        """Entity with confidence outside [0.0, 1.0] raises."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "description": "Bad confidence", "confidence": 1.5}
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "confidence' must be in range [0.0, 1.0]" in exc_info.value.errors[0]
    
    def test_entity_confidence_wrong_type_raises(self):
        """Entity with non-numeric confidence raises."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "description": "Bad confidence type", "confidence": "high"}
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "'confidence' must be a number" in exc_info.value.errors[0]
    
    def test_entity_capitalized_fields_accepted(self):
        """Entity with capitalized field names (Id, Type, Description) is accepted."""
        ontology = {
            "entities": [
                {"Id": "e1", "Type": "Person", "Description": "Capitalized fields", "Confidence": 0.9}
            ],
            "relationships": [],
        }
        # Should not raise
        validate_ontology_schema(ontology)


class TestRelationshipValidation:
    """Test relationship structure validation."""
    
    def test_valid_relationship(self):
        """Valid relationship passes validation."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "description": "Alice"},
                {"id": "e2", "type": "Person", "description": "Bob"},
            ],
            "relationships": [
                {
                    "source": "e1",
                    "target": "e2",
                    "type": "knows",
                    "confidence": 0.85,
                }
            ],
        }
        # Should not raise
        validate_ontology_schema(ontology)
    
    def test_relationship_without_confidence_passes_non_strict(self):
        """Relationship without confidence passes in non-strict mode."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "description": "Alice"},
                {"id": "e2", "type": "Person", "description": "Bob"},
            ],
            "relationships": [
                {"source": "e1", "target": "e2", "type": "knows"}
            ],
        }
        # Should not raise
        validate_ontology_schema(ontology, strict=False)
    
    def test_relationship_without_confidence_fails_strict(self):
        """Relationship without confidence fails in strict mode."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "description": "Alice"},
                {"id": "e2", "type": "Person", "description": "Bob"},
            ],
            "relationships": [
                {"source": "e1", "target": "e2", "type": "knows"}
            ],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology, strict=True)
        
        assert "missing required field 'confidence'" in exc_info.value.errors[0]
    
    def test_relationship_non_dict_raises(self):
        """Relationship that is not a dict raises."""
        ontology = {
            "entities": [],
            "relationships": ["not a dict"],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "must be a dict" in exc_info.value.errors[0]
    
    def test_relationship_missing_source_raises(self):
        """Relationship missing 'source' field raises."""
        ontology = {
            "entities": [{"id": "e1", "type": "T", "description": "D"}],
            "relationships": [
                {"target": "e1", "type": "knows"}
            ],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "missing required field 'source'" in exc_info.value.errors[0]
    
    def test_relationship_missing_target_raises(self):
        """Relationship missing 'target' field raises."""
        ontology = {
            "entities": [{"id": "e1", "type": "T", "description": "D"}],
            "relationships": [
                {"source": "e1", "type": "knows"}
            ],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "missing required field 'target'" in exc_info.value.errors[0]
    
    def test_relationship_missing_type_raises(self):
        """Relationship missing 'type' field raises."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "T", "description": "D"},
                {"id": "e2", "type": "T", "description": "D"},
            ],
            "relationships": [
                {"source": "e1", "target": "e2"}
            ],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "missing required field 'type'" in exc_info.value.errors[0]
    
    def test_relationship_invalid_source_reference_raises(self):
        """Relationship referencing non-existent source entity raises."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "T", "description": "D"},
            ],
            "relationships": [
                {"source": "e_nonexistent", "target": "e1", "type": "knows"}
            ],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology, check_references=True)
        
        assert "references non-existent entity 'e_nonexistent'" in exc_info.value.errors[0]
    
    def test_relationship_invalid_target_reference_raises(self):
        """Relationship referencing non-existent target entity raises."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "T", "description": "D"},
            ],
            "relationships": [
                {"source": "e1", "target": "e_nonexistent", "type": "knows"}
            ],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology, check_references=True)
        
        assert "references non-existent entity 'e_nonexistent'" in exc_info.value.errors[0]
    
    def test_relationship_invalid_reference_passes_when_check_disabled(self):
        """Invalid references pass when check_references=False."""
        ontology = {
            "entities": [],
            "relationships": [
                {"source": "e_nonexistent", "target": "e_also_missing", "type": "knows"}
            ],
        }
        # Should not raise
        validate_ontology_schema(ontology, check_references=False)
    
    def test_duplicate_relationship_ids_raises(self):
        """Duplicate relationship IDs raise."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "T", "description": "D"},
                {"id": "e2", "type": "T", "description": "D"},
            ],
            "relationships": [
                {"id": "r1", "source": "e1", "target": "e2", "type": "knows"},
                {"id": "r1", "source": "e2", "target": "e1", "type": "knows"},
            ],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        assert "duplicate relationship ID 'r1'" in exc_info.value.errors[0]
    
    def test_relationship_capitalized_fields_accepted(self):
        """Relationship with capitalized field names is accepted."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "T", "description": "D"},
                {"id": "e2", "type": "T", "description": "D"},
            ],
            "relationships": [
                {"Source": "e1", "Target": "e2", "Type": "knows", "Confidence": 0.8}
            ],
        }
        # Should not raise
        validate_ontology_schema(ontology)


class TestMultipleErrors:
    """Test that all errors are collected and reported."""
    
    def test_multiple_entity_errors_collected(self):
        """Multiple entity validation errors are collected."""
        ontology = {
            "entities": [
                {"id": "e1"},  # Missing type and description
                {"type": "T", "description": "D"},  # Missing id
            ],
            "relationships": [],
        }
        with pytest.raises(OntologySchemaError) as exc_info:
            validate_ontology_schema(ontology)
        
        # Should have at least 3 errors
        assert len(exc_info.value.errors) >= 3
        error_messages = " ".join(exc_info.value.errors)
        assert "missing required field 'type'" in error_messages
        assert "missing required field 'description'" in error_messages
        assert "missing required field 'id'" in error_messages


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
